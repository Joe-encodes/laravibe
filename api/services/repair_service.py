"""
api/services/repair_service.py — Iterative repair loop orchestrator.

Wires together: sandbox_service, docker_service, boost_service, ai_service, patch_service.
Runs as an async generator yielding SSE event dicts.
Each iteration: container → execute → boost → AI fix → patch → re-run.

This file is the ORCHESTRATOR only. All container interaction logic lives in
sandbox_service.py. All AI/LLM logic lives in ai_service.py.
"""
import json
import logging
import re
import time
import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from api.config import get_settings
from api.models import Submission, Iteration
from api.services import docker_service, boost_service, ai_service, patch_service, sandbox_service, escalation_service, context_service
from api.services.ai_service import AIServiceError
from api.services.patch_service import PatchApplicationError, strip_markdown_fences, ApplyAllResult

logger = logging.getLogger(__name__)
settings = get_settings()

# How many identical AI diagnoses before we force a strategy shift
STUCK_LOOP_THRESHOLD = 3


def _now():
    return datetime.now(timezone.utc)


def _evt(event: str, **data) -> dict:
    """Build a SSE event dict."""
    return {"event": event, "data": data}


def _normalize_code(code: str) -> str:
    """Strip CRLF line endings and UTF-8 BOM from Windows-origin code."""
    result = code.replace('\r\n', '\n').replace('\r', '\n')
    if result.startswith('\ufeff'):
        result = result[1:]
    return result


async def run_repair_loop(
    submission_id: str,
    code: str,
    db: AsyncSession,
    prompt: str | None = None,
    max_iterations: int | None = None,
    use_boost: bool = True,
    use_mutation_gate: bool = True,
) -> AsyncGenerator[dict, None]:
    """
    Async generator — yields SSE event dicts while repairing.
    Final event is always "complete" (status=success|failed).
    """
    max_iter = max_iterations or settings.max_iterations
    current_code = _normalize_code(code)
    previous_attempts: list[dict] = []
    current_pest_test: str | None = None
    initial_error_text: str | None = None

    ctx_log = logging.LoggerAdapter(logger, {"submission_id": submission_id})
    ctx_log.info("Starting repair process")

    yield _evt("submission_start", id=submission_id, prompt=prompt)

    # Mark submission as running
    submission = await db.get(Submission, submission_id)
    if not submission:
        yield _evt("error", message=f"Submission {submission_id} not found")
        return
    submission.status = "running"
    await db.commit()

    container = None
    try:
        # ── 1. Create container & health check (ONCE) ─────────────────
        yield _evt("log_line", msg="Spinning up sandbox container...")
        container = await docker_service.create_container()
        if not await docker_service.ping(container):
            yield _evt("log_line", msg="❌ Sandbox not responsive.")
            raise Exception("Sandbox container created but not responsive.")

        yield _evt("log_line", msg="🗄️ Configuring SQLite...")
        await sandbox_service.setup_sqlite(container)

        for iteration_num in range(max_iter):
            iteration_id = str(uuid.uuid4())
            iter_start = time.monotonic()
            yield _evt("iteration_start", iteration=iteration_num + 1, max=max_iter)

            try:
                # ── 2. Prepare sandbox (overwrite code.php ) ──────────────
                await docker_service.copy_code(container, current_code)

                # ── 3. Lint → Place → Scaffold (scaffold BEFORE boost so routes are visible) ──
                yield _evt("log_line", msg="Executing code...")
                class_info = None
                lint = await docker_service.execute(container, "php -l /submitted/code.php 2>&1", timeout=10)

                if lint.exit_code != 0:
                    exec_result = lint
                else:
                    class_info = await sandbox_service.detect_class_info(container)
                    exec_result = await sandbox_service.place_code_in_laravel(container, class_info, should_migrate=True)
                    # Scaffold route BEFORE boost context fetch so route:list sees the registered route
                    await sandbox_service.scaffold_route(container, class_info)

                # ── 4. Test if code works ─────────────────────────────────────
                if exec_result.exit_code == 0 and not exec_result.has_php_fatal:
                    # Inject system-controlled baseline test as PRIMARY correctness gate.
                    baseline_test = sandbox_service.generate_baseline_pest_test(class_info)
                    await sandbox_service.inject_pest_test(container, baseline_test)

                    yield _evt("log_line", msg="✅ Code loaded. Running Pest...")
                    pest_result = await sandbox_service.run_pest_test(container)

                    if pest_result.exit_code == 0:
                        yield _evt("pest_result", status="pass", output=pest_result.stdout[:2000])

                        # ── 4a. Mutation gate ──────────────────────────────────
                        is_genuine = True
                        mutation_score = None
                        if use_mutation_gate:
                            # Require AI-generated test with covers() before running mutation gate.
                            if current_pest_test:
                                yield _evt("log_line", msg="🔍 Linting AI test...")
                                await sandbox_service.inject_pest_test(container, current_pest_test)
                                lint_res = await sandbox_service.lint_test_file(container)
                                
                                if lint_res.exit_code != 0:
                                    is_genuine = False
                                    mutation_score = 0.0
                                    error_text = f"TEST_SYNTAX_ERROR: Your generated Pest test has a syntax error:\n{lint_res.stdout}"
                                    yield _evt("log_line", msg="❌ AI test syntax error.")
                                    yield _evt("mutation_result", score=0.0, threshold=settings.mutation_score_threshold,
                                               passed=False, output=lint_res.stdout, duration_ms=lint_res.duration_ms)
                                else:
                                    yield _evt("log_line", msg=f"🧬 Mutation tests (threshold: {settings.mutation_score_threshold}%)...")
                                    mut = await sandbox_service.run_mutation_test(container)
                                    mutation_score = mut.score
                                    is_genuine = mut.passed
                                    # Accept low mutation if last action was create_file
                                    if not is_genuine and previous_attempts and previous_attempts[-1].get("action") == "create_file":
                                        is_genuine = True
                                        mutation_score = 100.0
                                    yield _evt("mutation_result", score=mut.score, threshold=settings.mutation_score_threshold,
                                               passed=is_genuine, output=mut.output, duration_ms=mut.duration_ms)
                            else:
                                # No AI test yet — skip mutation gate, accept the baseline pass
                                yield _evt("log_line", msg="⏩ No AI-generated test — skipping mutation gate (baseline pass).")
                                is_genuine = True
                                mutation_score = None
                        else:
                            yield _evt("log_line", msg="⏩ Mutation gate disabled.")

                        if is_genuine:
                            # 🎉 SUCCESS
                            if initial_error_text and previous_attempts:
                                failed_deps = [a.get("diagnosis", "") for a in previous_attempts[:-1] if a.get("diagnosis", "")]
                                last_attempt = previous_attempts[-1]
                                await context_service.store_repair_summary(
                                    db=db,
                                    error_text=initial_error_text,
                                    diagnosis=last_attempt.get("diagnosis", ""),
                                    fix_applied=last_attempt.get("fix_description", ""),
                                    failed_diagnoses=failed_deps,
                                    iterations_needed=iteration_num + 1
                                )

                            await _save_iteration(db, iteration_id, submission_id, iteration_num,
                                current_code, exec_result, pest_result.stdout, mutation_score, "success",
                                int((time.monotonic() - iter_start) * 1000))
                            submission.status = "success"
                            submission.final_code = current_code
                            submission.total_iterations = iteration_num + 1
                            await db.commit()
                            yield _evt("complete", status="success", final_code=current_code,
                                       iterations=iteration_num + 1, mutation_score=mutation_score)
                            return

                        # Mutation too low
                        error_text = (
                            f"MUTATION_WEAK: score {mutation_score:.1f}% (need {settings.mutation_score_threshold}%). "
                            f"Strengthen the implementation and make the Pest test more precise."
                        )
                        if initial_error_text is None:
                            initial_error_text = error_text
                        yield _evt("log_line", msg=f"⚠️ Mutation {mutation_score:.1f}% too low.")
                    else:
                        pest_output = pest_result.stdout + pest_result.stderr
                        logger.warning(f"[PEST FAIL] output:\n{pest_output[:600]}")
                        # Capture the underlying Laravel exception from app logs.
                        laravel_log = await sandbox_service.capture_laravel_log(container)
                        error_text = pest_output
                        if laravel_log and "No laravel log" not in laravel_log:
                            error_text += f"\n\n=== Laravel application log (last 40 lines) ===\n{laravel_log}"
                            
                        # Detect if the test crashed due to a missing dependency / factory / namespace
                        crash_markers = ["not found", "doesn't exist", "does not exist", "ReflectionException", "Call to undefined method"]
                        if any(m in error_text for m in crash_markers):
                             error_text = f"TEST_DEPENDENCY_ERROR: Your test crashed because a class, method, or factory is missing or called incorrectly. Use create_file if you need to create a Factory or Model. Check your namespaces.\n\n" + error_text

                        if initial_error_text is None:
                            initial_error_text = error_text
                        yield _evt("pest_result", status="fail", output=error_text[:2000], duration_ms=pest_result.duration_ms)
                        yield _evt("log_line", msg="❌ Pest failed.")
                else:
                    error_text = exec_result.stderr + exec_result.stdout
                    if initial_error_text is None:
                        initial_error_text = error_text
                    yield _evt("log_line", msg=f"❌ Execution error (exit={exec_result.exit_code})")

                # ── 5. Boost context ──────────────────────────────────────────
                boost_ctx_json = "{}"
                if use_boost:
                    yield _evt("log_line", msg="Querying Boost context...")
                    boost_ctx_json = await boost_service.query_context(container, error_text, submission_id=submission_id)
                    boost_ctx = json.loads(boost_ctx_json)
                    yield _evt("boost_queried", schema=bool(boost_ctx.get("schema_info")),
                               component_type=boost_ctx.get("component_type"))
                else:
                    yield _evt("log_line", msg="⏩ Boost disabled.")

                # ── 6. Stuck-loop detection ───────────────────────────────────
                escalation_ctx = escalation_service.build_escalation_context(previous_attempts)
                if escalation_ctx:
                    yield _evt("log_line", msg="⚠️ Stuck loop detected. Escalating AI prompt.")

                # ── 7. Call AI ────────────────────────────────────────────────
                similar_repairs = ""
                if initial_error_text:
                    similar_repairs = await context_service.retrieve_similar_repairs(db, initial_error_text)

                yield _evt("ai_thinking", msg="Sending to AI...")
                ctx_log.info(f"\n{'='*20} BOOST CONTEXT {'='*20}\n{boost_ctx_json}\n{'='*54}")
                try:
                    ai_resp = await ai_service.get_repair(
                        code=current_code, error=error_text, boost_context=boost_ctx_json,
                        iteration=iteration_num, previous_attempts=previous_attempts,
                        escalation_context=escalation_ctx, similar_past_repairs=similar_repairs,
                        user_prompt=prompt
                    )
                    ctx_log.info(f"\n{'='*20} AI RESPONSE {'='*20}\n{ai_resp.raw}\n{'='*52}")
                except AIServiceError as exc:
                    yield _evt("error", msg=f"🚫 AI failed: {exc}")
                    submission.status = "failed"
                    submission.error_summary = f"AI error: {exc}"
                    await db.commit()
                    yield _evt("complete", status="failed", iterations=iteration_num + 1, message=str(exc))
                    return

                yield _evt("ai_thinking", diagnosis=ai_resp.diagnosis, fix_description=ai_resp.fix_description, thought_process=ai_resp.thought_process)

                # ── 7b. Ensure Pest test has covers() ─────────────────────────
                if ai_resp.pest_test:
                    fqcn_ref = class_info.fqcn if class_info else None
                    ai_resp.pest_test = sandbox_service.ensure_covers_directive(
                        ai_resp.pest_test, current_code, fqcn_ref)

                # ── 8. Apply patch(es) via apply_all ─────────────────────────────
                patch_status = "applied"
                actions_taken = []
                try:
                    patch_result: ApplyAllResult = patch_service.apply_all(current_code, ai_resp.patches)
                    current_code = patch_result.updated_code
                    actions_taken = patch_result.actions_taken

                    # Log any forbidden files that were blocked
                    for blocked in patch_result.skipped_forbidden:
                        yield _evt("log_line", msg=f"🚫 Blocked forbidden target: {blocked}")

                    # Handle created files (Models, Migrations, etc.)
                    for rel_path, content in patch_result.created_files.items():
                        yield _evt("log_line", msg=f"📝 Creating: {rel_path}")
                        await docker_service.copy_file(container, f"/var/www/sandbox/{rel_path}", content)

                    if patch_result.created_files:
                        # Flush autoloader + run migrations once for all created files
                        await docker_service.execute(container, "cd /var/www/sandbox && composer dump-autoload -q")
                        mig_res = await docker_service.execute(
                            container,
                            "cd /var/www/sandbox && php artisan migrate --force --no-interaction && php artisan optimize:clear > /dev/null",
                            user="root"
                        )
                        if mig_res.exit_code != 0:
                            yield _evt("log_line", msg=f"⚠️ Migration/Optimize failed: {mig_res.stderr}")

                    if ai_resp.pest_test:
                        current_pest_test = ai_resp.pest_test
                        await sandbox_service.inject_pest_test(container, current_pest_test)

                    action_str = " + ".join(actions_taken) if actions_taken else "none"
                    yield _evt("patch_applied", action=action_str, fix=ai_resp.fix_description)
                except PatchApplicationError as exc:
                    patch_status = f"FAILED — {exc}"
                    yield _evt("log_line", msg=f"⚠️ Patch failed: {exc}")
                    error_text += f"\n\nPATCH_FAILED: {exc}"

                # ── 9. Track & persist ────────────────────────────────────────
                previous_attempts.append({
                    "action": " + ".join(actions_taken) if actions_taken else "none",
                    "patch_status": patch_status,
                    "diagnosis": ai_resp.diagnosis,
                    "fix_description": ai_resp.fix_description,
                })
                await _save_iteration(db, iteration_id, submission_id, iteration_num,
                    current_code, exec_result, None, None, "failed",
                    int((time.monotonic() - iter_start) * 1000),
                    boost_ctx_json=boost_ctx_json, ai_prompt=ai_resp.prompt,
                    ai_response=ai_resp.raw, patch_applied=str([vars(p) for p in ai_resp.patches]),
                    pest_test_code=ai_resp.pest_test, error_logs=error_text)
                submission.total_iterations = iteration_num + 1
                await db.commit()

            except Exception as exc:
                ctx_log.exception(f"[Repair] Iteration {iteration_num} crashed: {exc}")
                yield _evt("error", msg=f"💥 Iteration {iteration_num + 1}: {type(exc).__name__}: {exc}")

        # Loop exhausted
        submission.status = "failed"
        submission.error_summary = f"Could not repair after {max_iter} iterations."
        await db.commit()
        yield _evt("complete", status="failed", iterations=max_iter,
                   message=f"Repair failed after {max_iter} iterations.")

    finally:
        if container:
            await docker_service.destroy(container)


async def _save_iteration(
    db: AsyncSession, iteration_id: str, submission_id: str, iteration_num: int,
    code_input: str, exec_result, pest_test_result: str | None,
    mutation_score: float | None, status: str, duration_ms: int,
    boost_ctx_json: str | None = None, ai_prompt: str | None = None,
    ai_response: str | None = None, patch_applied: str | None = None,
    pest_test_code: str | None = None, error_logs: str | None = None,
) -> None:
    """Persist a single iteration record to the database."""
    db.add(Iteration(
        id=iteration_id, submission_id=submission_id, iteration_num=iteration_num,
        code_input=code_input,
        execution_output=exec_result.stdout[:5000] if exec_result else None,
        error_logs=(error_logs or ((exec_result.stderr + exec_result.stdout)[:5000] if exec_result else None)),
        boost_context=boost_ctx_json, ai_prompt=ai_prompt, ai_response=ai_response,
        patch_applied=patch_applied, pest_test_code=pest_test_code,
        pest_test_result=pest_test_result, mutation_score=mutation_score,
        status=status, duration_ms=duration_ms, created_at=_now(),
    ))
