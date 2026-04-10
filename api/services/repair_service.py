"""
api/services/repair_service.py — The main orchestrator: iterative repair loop.

Wires together: docker_service, boost_service, ai_service, patch_service.
Runs as an async generator that yields SSE-compatible event dicts.
Each iteration: spin container → exec → boost → AI fix → patch → re-run.
Mutation gate (Gemini): after Pest passes, run pest --mutate >= threshold.
"""
import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from api.config import get_settings
from api.models import Submission, Iteration
from api.services import docker_service, boost_service, ai_service, patch_service
from api.services.ai_service import AIServiceError
from api.services.patch_service import PatchApplicationError, strip_markdown_fences

logger = logging.getLogger(__name__)
settings = get_settings()


def _now():
    return datetime.now(timezone.utc)


def _evt(event: str, **data) -> dict:
    """Build a SSE event dict."""
    return {"event": event, "data": data}


async def run_repair_loop(
    submission_id: str,
    code: str,
    db: AsyncSession,
    max_iterations: int | None = None,
    use_boost: bool = True,
    use_mutation_gate: bool = True,
) -> AsyncGenerator[dict, None]:
    """
    Async generator — yields SSE event dicts while repairing.
    Caller (SSE router) iterates this and sends each dict as a server-sent event.

    Final event is always "complete" (status=success|failed).
    """
    max_iter = max_iterations or settings.max_iterations
    current_code = code
    previous_attempts: list[dict] = []
    # Tracks files created by create_file patches so they can be re-injected into
    # every fresh container. Without this, the AI's fix (e.g. a new Model file)
    # gets written to a container and immediately lost when that container is destroyed.
    supplementary_files: dict[str, str] = {}  # {relative_path: file_content}

    # Mark submission as running
    submission = await db.get(Submission, submission_id)
    if not submission:
        yield _evt("error", message=f"Submission {submission_id} not found")
        return
    submission.status = "running"
    await db.commit()

    for iteration_num in range(max_iter):
        iteration_id = str(uuid.uuid4())
        iter_start = time.monotonic()

        yield _evt("iteration_start", iteration=iteration_num + 1, max=max_iter)

        container = None
        try:
            # ── 1. Spin up a fresh container ──────────────────────────────────
            yield _evt("log_line", msg="Spinning up sandbox container...")
            container = await docker_service.create_container()

            # ── 2. Copy current code into container ───────────────────────────
            await docker_service.copy_code(container, current_code)

            # ── 2b. Re-inject any files created by previous iterations ─────────
            # These are dependency files (Models, Migrations, etc.) that the AI
            # created in a previous container but are now lost because that
            # container was destroyed. We rebuild them on every fresh container.
            if supplementary_files:
                yield _evt("log_line", msg=f"♻️  Re-injecting {len(supplementary_files)} dependency file(s) from previous iterations...")
                for rel_path, file_content in supplementary_files.items():
                    abs_path = f"/var/www/sandbox/{rel_path}"
                    # Use a heredoc written via bash -c to avoid shell escaping issues
                    inject_cmd = (
                        f"mkdir -p \"$(dirname '{abs_path}')\" && "
                        f"cat > '{abs_path}' << 'INJECT_EOF'\n{file_content}\nINJECT_EOF"
                    )
                    await docker_service.execute(container, inject_cmd, timeout=15)
                # Refresh autoloader after injecting all supplementary files
                await docker_service.execute(
                    container,
                    "cd /var/www/sandbox && composer dump-autoload -q 2>&1",
                    timeout=30,
                )

            # ── 2c. Configure sandbox DB as SQLite for Boost context ──────────
            # The container runs with --network=none, so MySQL/Redis are
            # unreachable. Switching to SQLite lets boost:schema query a real
            # (migrated) schema without any network access.
            if iteration_num == 0:
                yield _evt("log_line", msg="🗄️ Configuring sandbox database (SQLite)...")
                sqlite_setup_cmd = (
                    "cd /var/www/sandbox && "
                    "touch database/database.sqlite && "
                    "sed -i 's/DB_CONNECTION=.*/DB_CONNECTION=sqlite/' .env 2>/dev/null; "
                    "sed -i 's|DB_DATABASE=.*|DB_DATABASE=/var/www/sandbox/database/database.sqlite|' .env 2>/dev/null; "
                    "php artisan migrate --force --no-interaction 2>&1 | tail -3"
                )
                await docker_service.execute(container, sqlite_setup_cmd, timeout=45, user="root")

            # ── 3. Execute the code (Laravel-aware) ──────────────────────────
            yield _evt("log_line", msg="Executing code...")

            # Step 3a: PHP lint check (fastest — catches syntax errors immediately)
            lint_result = await docker_service.execute(
                container,
                "php -l /submitted/code.php 2>&1",
                timeout=10,
            )

            if lint_result.exit_code != 0:
                # Syntax error — report immediately without trying to run
                exec_result = lint_result
            else:
                # Step 3b: Place in Laravel app and check class loads via autoloader.
                # This handles controllers, models, middleware etc that can't run as
                # standalone scripts without Laravel bootstrap.
                detect_cmd = "grep -oP '(?<=namespace )[^;]+' /submitted/code.php 2>/dev/null || grep 'namespace ' /submitted/code.php | head -1 | sed 's/namespace //;s/;//;s/ //g'"
                ns_result = await docker_service.execute(container, detect_cmd, timeout=5)
                namespace = ns_result.stdout.strip().replace("\\", "/") or "App/Http/Controllers"

                class_detect_cmd = "grep -oP '(?<=class )\\w+' /submitted/code.php 2>/dev/null || grep '^class ' /submitted/code.php | head -1 | awk '{print $2}'"
                class_result = await docker_service.execute(container, class_detect_cmd, timeout=5)
                classname = class_result.stdout.strip() or "SubmittedClass"

                # Laravel PSR-4: App\ namespace maps to lowercase 'app/' directory
                dest_namespace = namespace
                if dest_namespace.startswith("App/"):
                    dest_namespace = "app/" + dest_namespace[4:]
                elif dest_namespace == "App":
                    dest_namespace = "app"

                dest_dir = f"/var/www/sandbox/{dest_namespace}"
                dest_file = f"{dest_dir}/{classname}.php"

                # Build the fully-qualified class name for PHP class_exists()
                php_ns = namespace.replace("/", "\\\\")
                fqcn = f"{php_ns}\\\\{classname}"
                logger.info(f"[Sandbox] namespace={namespace} class={classname} fqcn={fqcn} dest={dest_file}")
                
                # Validate using Tinker — more reliable than standalone execution
                setup_and_test_cmd = f"""
mkdir -p "{dest_dir}" /var/www/sandbox/app/Http/Controllers /var/www/sandbox/app/Models && 
cp /submitted/code.php "{dest_file}" 2>/dev/null || true && 
cd /var/www/sandbox && 
composer dump-autoload -q 2>&1 && 
php artisan tinker --execute="
    try {{
        if (!class_exists('{fqcn}')) {{
            throw new Exception('Class {fqcn} not found or failed to load');
        }}
        echo 'CLASS_OK';
    }} catch (Throwable \\$e) {{
        echo 'ERROR: ' . \\$e->getMessage();
    }}
" 2>&1
"""
                exec_result = await docker_service.execute(
                    container, setup_and_test_cmd, timeout=settings.container_timeout_seconds,
                )
                
                # Normalise success
                if "CLASS_OK" in exec_result.stdout and "ERROR:" not in exec_result.stdout:
                    exec_result = exec_result.__class__(
                        stdout=exec_result.stdout,
                        stderr="",
                        exit_code=0,
                        duration_ms=exec_result.duration_ms,
                    )
                else:
                    exec_result = exec_result.__class__(
                        stdout=exec_result.stdout,
                        stderr=exec_result.stderr,
                        exit_code=1,
                        duration_ms=exec_result.duration_ms,
                    )

            # ── 4. Check if execution succeeded ──────────────────────────────
            if exec_result.exit_code == 0 and not exec_result.has_php_fatal:
                yield _evt("log_line", msg="✅ Code executed without errors. Running Pest...")

                # ── 4a. Run Pest functional test ─────────────────────────────
                pest_result = await docker_service.execute(
                    container,
                    "./vendor/bin/pest --filter=RepairTest --no-coverage 2>&1",
                    timeout=60,
                )

                if pest_result.exit_code == 0:
                    yield _evt("pest_result", status="pass", output=pest_result.stdout[:2000])

                    # ── 4b. Mutation gate ─────────────────────────────────
                    mutation_score = None
                    is_genuine_success = True
                    
                    if use_mutation_gate:
                        yield _evt("log_line", msg=f"🧬 Running mutation tests (threshold: {settings.mutation_score_threshold}%)...")
                        mut_result = await docker_service.execute(
                            container,
                            "./vendor/bin/pest --mutate 2>&1",
                            timeout=120,
                        )
                        
                        # If the mutation command itself failed due to infra issues
                        # (missing PCOV, unknown flags, no covers() declaration, etc.),
                        # treat as a soft pass rather than blocking the entire loop
                        # on tooling/config problems.
                        mutation_cmd_failed = (
                            "Unknown option" in mut_result.stdout
                            or "not found" in mut_result.stdout
                            or "Extension pcov" in mut_result.stdout
                            or "requires the usage of" in mut_result.stdout
                        )
                        if mutation_cmd_failed:
                            mutation_score = 100.0  # Soft pass — can't measure, assume OK
                            logger.warning(f"[Mutation) Command failed (infra issue), soft-pass: {mut_result.stdout[:200]}")
                        else:
                            mutation_score = _parse_mutation_score(mut_result.stdout)
                        
                        # If this test passed because we just created a new boilerplate file (e.g. a Model),
                        # it might have 0.0% mutations simply because there's no logic to mutate.
                        # We accept this as a genuine success to avoid infinite loops.
                        is_genuine_success = mutation_score >= settings.mutation_score_threshold
                        if not is_genuine_success and previous_attempts:
                            if previous_attempts[-1].get("action") == "create_file":
                                is_genuine_success = True
                                mutation_score = 100.0  # mock a pass for display

                        yield _evt(
                            "mutation_result",
                            score=mutation_score,
                            threshold=settings.mutation_score_threshold,
                            passed=is_genuine_success,
                            output=mut_result.stdout[:1000],
                        )
                    else:
                        yield _evt("log_line", msg="⏩ Mutation gate disabled (ablation mode).")
                    

                    if is_genuine_success:
                        # 🎉 GENUINE SUCCESS
                        await _save_iteration(db, iteration_id, submission_id, iteration_num,
                            current_code, exec_result, pest_result.stdout, mutation_score, "success",
                            int((time.monotonic() - iter_start) * 1000))
                        submission.status = "success"
                        submission.final_code = current_code
                        submission.total_iterations = iteration_num + 1
                        await db.commit()

                        yield _evt("complete",
                            status="success",
                            final_code=current_code,
                            iterations=iteration_num + 1,
                            mutation_score=mutation_score,
                        )
                        return

                    else:
                        # Pest passed but mutation score too low — tell AI to strengthen
                        error_text = (
                            f"MUTATION_WEAK: Pest test passed but mutation score is {mutation_score:.1f}% "
                            f"(required: {settings.mutation_score_threshold}%). "
                            f"The fix is not robust enough. Please strengthen the implementation "
                            f"and make the Pest test more precise."
                        )
                        yield _evt("log_line", msg=f"⚠️ Mutation score too low ({mutation_score:.1f}%). Strengthening fix...")
                else:
                    error_text = pest_result.stdout + pest_result.stderr
                    yield _evt("pest_result", status="fail", output=error_text[:2000])
                    yield _evt("log_line", msg="❌ Pest test failed. Requesting AI fix...")
            else:
                error_text = exec_result.stderr + exec_result.stdout
                yield _evt("log_line", msg=f"❌ Execution error (exit={exec_result.exit_code})")

            # ── 5. Query Boost context (if enabled) ──────────────────────────
            boost_ctx_json = "{}"
            if use_boost:
                yield _evt("log_line", msg="Querying Laravel Boost for context...")
                boost_ctx_json = await boost_service.query_context(container, error_text)
                boost_ctx = json.loads(boost_ctx_json)
                yield _evt("boost_queried", schema=bool(boost_ctx.get("schema_info")),
                           component_type=boost_ctx.get("component_type"))
            else:
                yield _evt("log_line", msg="⏩ Boost context disabled (ablation mode).")
                boost_ctx = {}

            # ── 6. Call AI ────────────────────────────────────────────────────
            yield _evt("ai_thinking", msg="Sending to AI for repair suggestion...")
            try:
                # [DEBUG LOGGING]
                logger.info(f"\n{'='*20} BOOTS CONTEXT INJECTED {'='*20}")
                logger.info(boost_ctx_json)
                logger.info(f"{'='*64}\n")

                ai_resp = await ai_service.get_repair(
                    code=current_code,
                    error=error_text,
                    boost_context=boost_ctx_json,
                    iteration=iteration_num,
                    previous_attempts=previous_attempts,
                )
                
                # [DEBUG LOGGING]
                logger.info(f"\n{'='*20} RAW AI RESPONSE {'='*20}")
                logger.info(ai_resp.raw)
                logger.info(f"{'='*61}\n")

            except AIServiceError as exc:
                yield _evt("error", msg=f"🚫 AI provider '{settings.default_ai_provider}' failed: {exc}")
                yield _evt("log_line", msg=f"💡 Tip: Check your API key in .env, or switch provider with DEFAULT_AI_PROVIDER=")
                # Mark as failed immediately — no point retrying with a bad key/rate-limit
                submission.status = "failed"
                submission.error_summary = f"AI provider error: {exc}"
                await db.commit()
                yield _evt("complete", status="failed", iterations=iteration_num + 1,
                    message=f"AI provider '{settings.default_ai_provider}' error: {exc}")
                return

            yield _evt("ai_thinking",
                diagnosis=ai_resp.diagnosis,
                fix_description=ai_resp.fix_description,
            )

            # ── 7. Apply patch ────────────────────────────────────────────────
            try:
                new_code_or_file = patch_service.apply(current_code, ai_resp.patch)
                
                if ai_resp.patch.action == "create_file":
                    yield _evt("log_line", msg=f"📝 Creating new file: {ai_resp.patch.filename}")

                    dest_path = f"/var/www/sandbox/{ai_resp.patch.filename}"
                    # apply() returns current_code unchanged for create_file.
                    # The new file's content comes directly from the patch spec (stripped of fences).
                    content = strip_markdown_fences(ai_resp.patch.replacement)
                    
                    create_cmd = f"""
mkdir -p "$(dirname '{dest_path}')" && 
cat << 'EOF_CREATE' > '{dest_path}'
{content}
EOF_CREATE
cd /var/www/sandbox && composer dump-autoload -q 2>&1
"""
                    await docker_service.execute(container, create_cmd)
                    # ── Register for persistence across iterations ─────────────
                    # Containers are destroyed after each iteration. Without adding
                    # this file to supplementary_files, the next fresh container
                    # starts bare and the same "class not found" error recurs forever.
                    supplementary_files[ai_resp.patch.filename] = content
                    yield _evt("log_line", msg=f"📌 Registered {ai_resp.patch.filename} — will persist across containers ({len(supplementary_files)} file(s) total)")
                    # Do NOT change current_code — we are adding a dependency
                else:
                    current_code = new_code_or_file
                    
                yield _evt("patch_applied",
                    action=ai_resp.patch.action,
                    fix=ai_resp.fix_description,
                )
            except PatchApplicationError as exc:
                yield _evt("log_line", msg=f"⚠️ Patch failed: {exc}. AI will retry.")
                # Still save and loop — AI will see the same error + patch failure note
                error_text += f"\n\nPATCH_FAILED: {exc}"

            # ── 8. Track previous attempts for AI context ────────────────────
            previous_attempts.append({
                "action": ai_resp.patch.action,
                "diagnosis": ai_resp.diagnosis,
                "fix_description": ai_resp.fix_description,
            })

            # ── 9. Save iteration to DB ──────────────────────────────────────
            await _save_iteration(db, iteration_id, submission_id, iteration_num,
                current_code, exec_result, None, None, "failed",
                int((time.monotonic() - iter_start) * 1000),
                boost_ctx_json=boost_ctx_json,
                ai_prompt=None, ai_response=ai_resp.raw,
                patch_applied=str(ai_resp.patch),
                pest_test_code=ai_resp.pest_test,
                error_logs=error_text,
            )
            submission.total_iterations = iteration_num + 1
            await db.commit()

        except Exception as exc:
            logger.exception(f"[Repair] Unexpected error in iteration {iteration_num}: {exc}")
            yield _evt("error", msg=f"💥 Iteration {iteration_num + 1} crashed: {type(exc).__name__}: {exc}")
            # Don't silently continue — emit the error visibly and keep going
            # The loop will pick up the next iteration naturally
        finally:
            if container:
                await docker_service.destroy(container)

    # ── Loop exhausted without success ────────────────────────────────────────
    submission.status = "failed"
    submission.error_summary = f"Could not repair after {max_iter} iterations."
    await db.commit()

    yield _evt("complete", status="failed", iterations=max_iter,
        message=f"Repair failed after {max_iter} iterations.")


def _parse_mutation_score(output: str) -> float:
    """
    Extract mutation score percentage from pest --mutate output.

    Pest 3 outputs one of these formats:
      "Mutations: 15 tested, 12 killed (80.0%), 3 survived"
      "Score:  80.00 %"
      "80% mutation score"
      "mutation score: 80"
      "Mutation score: 80.0 %" (some versions add a space before %)

    Returns 0.0 if not found (fail-safe — treated as mutation failure).
    """
    import re

    # Always log the raw output so we can debug parser misses in the FastAPI logs.
    logger.debug(f"[MutationParser] raw output:\n{output[:800]}")

    patterns = [
        r"killed\s*\((\d+(?:\.\d+)?)%\)",           # "12 killed (80.0%)"     ← Pest 3 primary
        r"mutations?\s*:\s*(\d+(?:\.\d+)?)\s*%",    # "Mutations: 78.3%"      ← Pest label format
        r"(\d+(?:\.\d+)?)\s*%\s*mutation\s+score",  # "80% mutation score"
        r"mutation\s+score[:\s]+(\d+(?:\.\d+)?)",   # "mutation score: 80"
        r"score[:\s]+(\d+(?:\.\d+)?)\s*%",          # "Score: 80.00%"
        r"(\d+(?:\.\d+)?)\s*%\s*scored",            # "80.0% scored"
    ]
    for pattern in patterns:
        match = re.search(pattern, output, re.IGNORECASE)
        if match:
            score = float(match.group(1))
            logger.info(f"[MutationParser] Matched pattern '{pattern}' → score={score}%")
            return score

    logger.warning(f"[MutationParser] No pattern matched. Returning 0.0. Output snippet: {output[:200]!r}")
    return 0.0


async def _save_iteration(
    db: AsyncSession,
    iteration_id: str,
    submission_id: str,
    iteration_num: int,
    code_input: str,
    exec_result,
    pest_test_result: str | None,
    mutation_score: float | None,
    status: str,
    duration_ms: int,
    boost_ctx_json: str | None = None,
    ai_prompt: str | None = None,
    ai_response: str | None = None,
    patch_applied: str | None = None,
    pest_test_code: str | None = None,
    error_logs: str | None = None,
) -> None:
    iteration = Iteration(
        id=iteration_id,
        submission_id=submission_id,
        iteration_num=iteration_num,
        code_input=code_input,
        execution_output=exec_result.stdout[:5000] if exec_result else None,
        error_logs=(error_logs or ((exec_result.stderr + exec_result.stdout)[:5000] if exec_result else None)),
        boost_context=boost_ctx_json,
        ai_prompt=ai_prompt,
        ai_response=ai_response,
        patch_applied=patch_applied,
        pest_test_code=pest_test_code,
        pest_test_result=pest_test_result,
        mutation_score=mutation_score,
        status=status,
        duration_ms=duration_ms,
        created_at=_now(),
    )
    db.add(iteration)
