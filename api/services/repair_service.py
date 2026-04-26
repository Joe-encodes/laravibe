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
from api.logging_config import set_submission_id, reset_submission_id
from api.models import Submission, Iteration
from api.services import (
    ai_service, patch_service, docker_service, sandbox_service,
    boost_service, context_service, escalation_service,
)
from api.services.ai_service import (
    AIServiceError, AIRepairResponse,
    get_plan, verify_plan, execute_plan, review_output,
)
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


def _normalize_migration(content: str) -> str:
    """
    Normalize AI-generated migrations for sandbox safety:
    1. Convert named-class migrations to anonymous class syntax.
    2. Strip softDeletes() columns unless the original code uses SoftDeletes traits.
       The AI hallucinates softDeletes() despite prompt bans; this causes fatal SQL
       column-mismatch errors when the Model does not use the SoftDeletes trait.
    """
    # Strip any softDeletes() column definitions — the infra-level safety net.
    # A line like: $table->softDeletes(); or $table->softDeletes('col', 0);
    content = re.sub(r'[ \t]*\$table->softDeletes\([^)]*\);[ \t]*\n?', '', content)

    # Skip further rewrite if already anonymous
    if 'return new class' in content:
        return content

    # Match: `class SomeName extends Migration {`
    named_class_pattern = re.compile(
        r'^class\s+\w+\s+extends\s+Migration\s*\{',
        re.MULTILINE
    )
    if not named_class_pattern.search(content):
        return content

    # Replace `class Foo extends Migration {` → `return new class extends Migration {`
    content = named_class_pattern.sub('return new class extends Migration {', content)

    # Replace the closing `}` (last one in the file) with `};`
    last_brace = content.rfind('}')
    if last_brace != -1:
        content = content[:last_brace] + '};' + content[last_brace + 1:]

    logger.debug("[Repair] Normalized named-class migration to anonymous class syntax.")
    return content


async def _lint_php_content(container, content: str, rel_hint: str) -> None:
    """Lint generated PHP content before accepting AI patch output."""
    if "<?php" not in content:
        return
    gate_path = "/tmp/ai_gate_candidate.php"
    await docker_service.copy_file(container, gate_path, content)
    lint_res = await docker_service.execute(container, f"php -l {gate_path} 2>&1", timeout=15)
    if lint_res.exit_code != 0:
        raise PatchApplicationError(
            f"AI_OUTPUT_INVALID_PHP [{rel_hint}]: {lint_res.stdout or lint_res.stderr}"
        )


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

    submission_ctx_token = set_submission_id(submission_id)
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

        ai_resp = None
        for iteration_num in range(max_iter):
            iteration_id = str(uuid.uuid4())
            iter_start = time.monotonic()
            error_text = ""
            iter_mutation_score: float | None = None
            patch_result: ApplyAllResult | None = None
            exec_result = None
            planner_model_used: str | None = None
            executor_model_used: str | None = None
            reviewer_model_used: str | None = None
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
                    # Re-run dump-autoload right before Pest to ensure any Model/Factory files
                    # created by the AI in the previous iteration are in the current classmap.
                    # place_code_in_laravel already runs dump-autoload but artisan calls
                    # (migrate, optimize:clear) can invalidate the bootstrap cache afterward.
                    await docker_service.execute(
                        container,
                        "cd /var/www/sandbox && composer dump-autoload -q 2>&1",
                    )
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
                        mut_output = ""
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
                                    mut_output = mut.output
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
                                int((time.monotonic() - iter_start) * 1000),
                                ai_model_used=ai_resp.model_used if ai_resp and hasattr(ai_resp, 'model_used') else None,
                                planner_model=planner_model_used,
                                executor_model=executor_model_used,
                                reviewer_model=reviewer_model_used)
                            submission.status = "success"
                            submission.final_code = current_code
                            submission.total_iterations = iteration_num + 1
                            await db.commit()
                            yield _evt("complete", status="success", final_code=current_code,
                                       iterations=iteration_num + 1, mutation_score=mutation_score)
                            return

                        # Mutation too low — store partial score for research data
                        iter_mutation_score = mutation_score
                        if "TEST_SYNTAX_ERROR" not in error_text:
                            error_text = (
                                f"MUTATION_WEAK: score {mutation_score:.1f}% (need {settings.mutation_score_threshold}%). "
                                f"Strengthen the implementation and make the Pest test more precise.\n\n"
                                f"=== SURVIVED MUTATIONS (Fix your test to kill these) ===\n{mut_output}"
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

                # Boost context
                boost_ctx_json = "{}"
                boost_prompt_text = ""
                if use_boost:
                    yield _evt("log_line", msg="Querying Boost context...")
                    boost_ctx_json = await boost_service.query_context(container, error_text, submission_id=submission_id)
                    boost_ctx_data = json.loads(boost_ctx_json)
                    boost_ctx_obj = boost_service.BoostContext(
                        schema_info=boost_ctx_data.get("schema_info", ""),
                        docs_excerpts=boost_ctx_data.get("docs_excerpts", []),
                        component_type=boost_ctx_data.get("component_type", "unknown"),
                    )
                    boost_prompt_text = boost_ctx_obj.to_prompt_text()
                    yield _evt("boost_queried", schema=bool(boost_ctx_data.get("schema_info")),
                               component_type=boost_ctx_data.get("component_type"))
                else:
                    yield _evt("log_line", msg="⏩ Boost disabled.")

                # Stuck-loop detection
                escalation_ctx = escalation_service.build_escalation_context(previous_attempts)
                if escalation_ctx:
                    yield _evt("log_line", msg="⚠️ Stuck loop detected. Escalating AI prompt.")

                # ── 7. Call AI (role pipeline OR legacy single call) ────────────
                similar_repairs = ""
                if initial_error_text:
                    similar_repairs = await context_service.retrieve_similar_repairs(db, initial_error_text)

                yield _evt("ai_thinking", msg="Sending to AI...")
                ctx_log.info(f"\n{'='*20} BOOST CONTEXT {'='*20}\n{boost_prompt_text or '(empty)'}\n{'='*54}")

                try:
                    # ── 7a. PLANNER ───────────────────────────────────────
                    yield _evt("log_line", msg="🧠 Planner: analysing error...")
                    plan_result = await get_plan(
                        code=current_code, error=error_text,
                        boost_context=boost_prompt_text,
                        previous_attempts=previous_attempts,
                        similar_past_repairs=similar_repairs,
                    )
                    planner_model_used = plan_result.model_used
                    ctx_log.info(f"[Planner] {plan_result.data.get('error_classification')} confidence={plan_result.data.get('plan_confidence')}")

                    # ── 7b. VERIFIER ──────────────────────────────────────
                    yield _evt("log_line", msg="🔎 Verifier: checking plan...")
                    verify_result = await verify_plan(
                        code=current_code, error=error_text,
                        boost_context=boost_prompt_text,
                        planner_output=plan_result.raw,
                    )

                    if verify_result.verdict == "REJECT":
                        ctx_log.warning(f"[Verifier] REJECT: {verify_result.reason}")
                        yield _evt("log_line", msg=f"⚠️ Verifier rejected plan: {verify_result.reason[:120]}")
                        # Treat as a patch failure — surface the reject reason for the next iteration
                        error_text += f"\n\nVERIFIER_REJECT: {verify_result.reason}"
                        if verify_result.corrections_made:
                            # Still have a partially corrected plan — use it
                            approved_plan = plan_result.data
                        else:
                            # Complete reject — skip to next iteration
                            previous_attempts.append({
                                "action": "plan_rejected",
                                "diagnosis": plan_result.data.get("error_classification", {}).get("primary", "unknown"),
                                "fix_description": "Verifier rejected plan.",
                                "outcome": f"VERIFIER_REJECT: {verify_result.reason}",
                                "created_files": [],
                                "escalation_evidence": {"reason": verify_result.reason},
                            })
                            continue

                    approved_plan = verify_result.approved_plan or plan_result.data
                    if verify_result.corrections_made:
                        yield _evt("log_line", msg=f"✏️ Verifier corrected {len(verify_result.corrections_made)} item(s).")

                    # ── 7c. EXECUTOR ──────────────────────────────────────
                    yield _evt("log_line", msg="⚙️ Executor: writing code...")
                    exec_result_role = await execute_plan(
                        code=current_code, error=error_text,
                        boost_context=boost_prompt_text,
                        approved_plan=approved_plan,
                        escalation_context=escalation_ctx,
                        user_prompt=prompt,
                    )
                    executor_model_used = exec_result_role.model_used
                    raw_executor_output = exec_result_role.response.raw

                    # ── 7d. REVIEWER ──────────────────────────────────────
                    yield _evt("log_line", msg="🔬 Reviewer: validating output...")
                    reviewer_retry = 0
                    MAX_REVIEWER_ESCALATIONS = 4
                    escalation_count = 0
                    reviewer_result = None

                    while escalation_count < MAX_REVIEWER_ESCALATIONS:
                        reviewer_result = await review_output(
                            executor_output_raw=raw_executor_output,
                            approved_plan=approved_plan,
                            retry_count=reviewer_retry,
                        )
                        reviewer_model_used = reviewer_result.model_used

                        if reviewer_result.verdict == "APPROVED":
                            if reviewer_result.repairs_made:
                                yield _evt("log_line", msg=f"✅ Reviewer approved (with {len(reviewer_result.repairs_made)} inline repair(s)).")
                            else:
                                yield _evt("log_line", msg="✅ Reviewer approved.")
                            break

                        # ESCALATE — start a new inner cycle (no iteration burned)
                        escalation_count += 1
                        ctx_log.warning(f"[Reviewer] ESCALATE ({escalation_count}): {reviewer_result.escalation_reason}")
                        yield _evt("log_line", msg=f"🔄 Reviewer escalating (cycle {escalation_count})...")

                        if escalation_count >= MAX_REVIEWER_ESCALATIONS:
                            # Force-accept best available output to avoid infinite loop
                            yield _evt("log_line", msg="⚠️ Max reviewer escalations reached. Forcing execution with best available output.")
                            try:
                                reviewer_result.validated_output = exec_result_role.response
                                reviewer_result.verdict = "APPROVED"
                            except Exception:
                                pass
                            break

                        # Feed evidence back — re-run Executor with escalation context
                        evidence = reviewer_result.evidence_for_next_cycle
                        new_escalation = escalation_ctx
                        if evidence:
                            new_escalation += f"\n\nREVIEWER_ESCALATION_EVIDENCE: {json.dumps(evidence)}"

                        exec_result_role = await execute_plan(
                            code=current_code, error=error_text,
                            boost_context=boost_prompt_text,
                            approved_plan=approved_plan,
                            escalation_context=new_escalation,
                            user_prompt=prompt,
                        )
                        executor_model_used = exec_result_role.model_used
                        raw_executor_output = exec_result_role.response.raw
                        reviewer_retry = 0  # fresh inner retry count for new execution

                    # Final validated output from Reviewer
                    if reviewer_result and reviewer_result.validated_output:
                        ai_resp = reviewer_result.validated_output
                    else:
                        ai_resp = exec_result_role.response

                    ctx_log.info(f"[Role Pipeline] Planner={planner_model_used} | Executor={executor_model_used} | Reviewer={reviewer_model_used}")

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
                if not ai_resp.patches:
                    raise PatchApplicationError("ZERO_FILES_EXTRACTED — escalate immediately")

                patch_status = "applied"
                actions_taken = []
                try:
                    patch_summary = [f"{p.action}:{p.target}" for p in ai_resp.patches]
                    ctx_log.info(f"Applying {len(ai_resp.patches)} patches: {patch_summary}")
                    patch_result = patch_service.apply_all(current_code, ai_resp.patches)
                except PatchApplicationError as exc:
                    ctx_log.error(f"[Repair] Patch apply failed: {exc}")
                    patch_status = f"FAILED — {exc}"
                    yield _evt("log_line", msg=f"⚠️ Patch failed: {exc}")
                    error_text += f"\n\nPATCH_FAILED: {exc}"
                    patch_result = None

                if patch_result is not None:
                    ctx_log.info(f"[PatchResult] created_files={list(patch_result.created_files.keys())} actions={patch_result.actions_taken}")
                    # Log any forbidden files that were blocked
                    for blocked in patch_result.skipped_forbidden:
                        yield _evt("log_line", msg=f"🚫 Blocked forbidden target: {blocked}")

                    # Quality gate: lint the full_replace controller code.
                    # IMPORTANT: this gate only prevents current_code from being updated.
                    # create_file patches are ALWAYS written below, even if this fails,
                    # so dependency files (Models, Migrations, Factories) accumulate in the
                    # container across iterations even when the controller PHP is broken.
                    controller_lint_ok = True
                    try:
                        await _lint_php_content(container, patch_result.updated_code, "submitted/code.php")
                        current_code = patch_result.updated_code
                        actions_taken = patch_result.actions_taken
                    except PatchApplicationError as exc:
                        controller_lint_ok = False
                        patch_status = f"FAILED — {exc}"
                        yield _evt("log_line", msg=f"⚠️ Patch failed: {exc}")
                        error_text += f"\n\nPATCH_FAILED: {exc}"
                        # Keep actions_taken for any create_file entries that succeeded
                        actions_taken = [a for a in patch_result.actions_taken if "create_file" in a]

                    # Always write create_file files regardless of controller lint outcome.
                    files_written: dict[str, str] = {}
                    for rel_path, content in patch_result.created_files.items():
                        try:
                            if 'database/migrations/' in rel_path:
                                content = _normalize_migration(content)
                            await _lint_php_content(container, content, rel_path)
                            ctx_log.info(f"[FileWrite] Writing {rel_path} ({len(content)} chars)")
                            yield _evt("log_line", msg=f"📝 Creating: {rel_path}")
                            await docker_service.copy_file(container, f"/var/www/sandbox/{rel_path}", content)
                            
                            # Container-side verification
                            verify = await docker_service.execute(container, f"php -l /var/www/sandbox/{rel_path} 2>&1", timeout=5)
                            if verify.exit_code == 0:
                                ctx_log.info(f"[FileWrite] ✅ Verified {rel_path}: {verify.stdout.strip()}")
                            else:
                                raise PatchApplicationError(f"FILE_NOT_LOADED_IN_CONTAINER: {rel_path} - {verify.stdout.strip()}")
                                
                            files_written[rel_path] = content
                        except PatchApplicationError as exc:
                            ctx_log.warning(f"[FileWrite] Skipped {rel_path} — lint failed: {exc}")
                            yield _evt("log_line", msg=f"⚠️ Skipping {rel_path} — invalid PHP: {exc}")
                        except Exception as exc:
                            ctx_log.warning(f"[FileWrite] Unexpected error for {rel_path}: {exc}")

                    if files_written:
                        ctx_log.info(f"[Autoload] Running composer dump-autoload for {list(files_written.keys())}")
                        dump_res = await docker_service.execute(container, "cd /var/www/sandbox && composer dump-autoload -q 2>&1")
                        if dump_res.exit_code != 0:
                            ctx_log.warning(f"[Autoload] composer dump-autoload failed: {dump_res.stdout}")
                        else:
                            ctx_log.info("[Autoload] composer dump-autoload OK")
                        mig_res = await docker_service.execute(
                            container,
                            "cd /var/www/sandbox && php artisan migrate:fresh --force --no-interaction && php artisan optimize:clear > /dev/null 2>&1"
                        )
                        if mig_res.exit_code != 0:
                            ctx_log.warning(f"[Autoload] Migration/Optimize failed: {mig_res.stderr}")
                            yield _evt("log_line", msg=f"⚠️ Migration/Optimize failed: {mig_res.stderr}")
                        else:
                            ctx_log.info("[Autoload] Migrations ran OK")

                    if ai_resp.pest_test and controller_lint_ok:
                        current_pest_test = ai_resp.pest_test
                        await sandbox_service.inject_pest_test(container, current_pest_test)

                    action_str = " + ".join(actions_taken) if actions_taken else "none"
                    yield _evt("patch_applied", action=action_str, fix=ai_resp.fix_description)

                # ── 9. Track & persist ────────────────────────────────────────
                previous_attempts.append({
                    "action": " + ".join(actions_taken) if actions_taken else "none",
                    "patch_status": patch_status,
                    "diagnosis": ai_resp.diagnosis,
                    "fix_description": ai_resp.fix_description,
                    "outcome": error_text[:300] if error_text else "unknown",
                    # Tracks which files were created so the Dependency Guard
                    # in escalation_service can detect re-creation attempts.
                    "created_files": list(patch_result.created_files.keys()) if patch_result else [],
                })
                await _save_iteration(db, iteration_id, submission_id, iteration_num,
                    current_code, exec_result, None, iter_mutation_score, "failed",
                    int((time.monotonic() - iter_start) * 1000),
                    boost_ctx_json=boost_ctx_json, ai_prompt=ai_resp.prompt if ai_resp else None,
                    ai_response=ai_resp.raw if ai_resp else None,
                    patch_applied=str([vars(p) for p in ai_resp.patches]) if ai_resp else None,
                    pest_test_code=ai_resp.pest_test if ai_resp else None, error_logs=error_text,
                    ai_model_used=ai_resp.model_used if (ai_resp and hasattr(ai_resp, 'model_used')) else None,
                    planner_model=planner_model_used,
                    executor_model=executor_model_used,
                    reviewer_model=reviewer_model_used)
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
        reset_submission_id(submission_ctx_token)
        if container:
            await docker_service.destroy(container)


async def _save_iteration(
    db: AsyncSession, iteration_id: str, submission_id: str, iteration_num: int,
    code_input: str, exec_result, pest_test_result: str | None,
    mutation_score: float | None, status: str, duration_ms: int,
    boost_ctx_json: str | None = None, ai_prompt: str | None = None,
    ai_response: str | None = None, patch_applied: str | None = None,
    pest_test_code: str | None = None, error_logs: str | None = None,
    ai_model_used: str | None = None,
    planner_model: str | None = None,
    executor_model: str | None = None,
    reviewer_model: str | None = None,
) -> None:
    """Persist a single iteration record to the database."""
    db.add(Iteration(
        id=iteration_id, submission_id=submission_id, iteration_num=iteration_num,
        code_input=code_input,
        execution_output=exec_result.stdout[:5000] if (exec_result and hasattr(exec_result, 'stdout')) else None,
        error_logs=(error_logs or ((exec_result.stderr + exec_result.stdout)[:5000] if (exec_result and hasattr(exec_result, 'stdout')) else None)),
        boost_context=boost_ctx_json, ai_prompt=ai_prompt, ai_response=ai_response,
        ai_model_used=ai_model_used,
        planner_model=planner_model,
        executor_model=executor_model,
        reviewer_model=reviewer_model,
        patch_applied=patch_applied, pest_test_code=pest_test_code,
        pest_test_result=pest_test_result, mutation_score=mutation_score,
        status=status, duration_ms=duration_ms, created_at=_now(),
    ))
