
import asyncio
import json
import logging
import time
from typing import AsyncGenerator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import re

from api.config import get_settings
from api.models import Submission, Iteration
import api.services.boost_service as boost_service
import api.services.patch_service as patch_service
import api.services.escalation_service as escalation_service
import api.services.ai_service as ai_service
import api.services.sandbox as sandbox
from api.services.sandbox import discovery
from api.services.error_classifier import classify_error, format_classified_error_for_llm
from . import pipeline, context
from api.logging_config import set_submission_id

logger = logging.getLogger(__name__)
settings = get_settings()


async def run_repair_loop(
    submission_id: str,
    code: str,
    prompt: str | None = None,
    db: AsyncSession | None = None,
    **kwargs,
) -> AsyncGenerator[dict, None]:
    """Orchestrate one full repair lifecycle: sandbox → AI loop → persist results."""
    set_submission_id(submission_id)

    submission = (
        await db.execute(select(Submission).where(Submission.id == submission_id))
    ).scalar_one()
    submission.status = "running"
    await db.commit()

    # 0. Pre-flight Docker Check
    try:
        from api.services.sandbox import docker as _docker
        _docker._get_client().ping()
    except Exception as d_exc:
        logger.error(f"[{submission_id}] Docker engine unreachable: {d_exc}")
        yield {"event": "error", "data": {"msg": "Critical Error: Docker engine is unreachable. Please contact administrator."}}
        submission.status = "failed"
        submission.error_summary = "Docker engine unreachable"
        await db.commit()
        return

    previous_attempts: list[dict] = []
    created_files: set[str] = set()
    
    try:
        container_id = await sandbox.create_sandbox()
        submission.container_id = container_id
        await db.commit()
    except Exception as c_exc:
        logger.error(f"[{submission_id}] Failed to create sandbox: {c_exc}")
        yield {"event": "error", "data": {"msg": f"Failed to create sandbox: {c_exc}"}}
        submission.status = "failed"
        submission.error_summary = f"Sandbox creation failed: {c_exc}"
        await db.commit()
        return

    try:
        yield {"event": "log_line", "data": {"msg": f"Sandbox created: {container_id[:12]}...", "id": container_id}}
        container = sandbox.get_container(container_id)

        # ── Bootstrap the Laravel environment once ────────────────────────────
        await sandbox.setup_sqlite(container)
        
        from api.services.sandbox import docker
        await docker.copy_code(container, code)
        
        class_info = await sandbox.detect_class_info(container)
        placed = await sandbox.place_code_in_laravel(container, class_info)
        if not placed:
            logger.warning(f"[{submission_id}] Could not auto-place code. Continuing anyway.")
        await sandbox.scaffold_route(container, class_info)

        primary_target_file = class_info.dest_file
        current_post_mortem = ""

        # Build a placement hint for the LLM so it always knows the correct file to patch.
        # This is critical: without it, models fall back to patching the source fixture path
        # which causes "Cannot declare class X, already in use" in Pest when the PSR-4
        # autoloader has already loaded the class from its correct location.
        _rel_dest = class_info.dest_file.replace("/var/www/sandbox/", "")
        placement_hint = (
            f"\n\n## ⚠️  CRITICAL — Correct patch target\n"
            f"The class `{class_info.fqcn}` lives at `{_rel_dest}` inside the Laravel project.\n"
            f"ALL `<file>` patches MUST target `{_rel_dest}`. "
            f"NEVER patch `tests/fixtures/` paths — those are read-only source files.\n"
        )

        yield {"event": "log_line", "data": {"msg": f"Class detected: {class_info.fqcn} → {_rel_dest}"}}

        # ── Repair loop ───────────────────────────────────────────────────────
        max_iters = kwargs.get("max_iterations") or settings.max_iterations
        for i in range(max_iters):
            start_time = time.time()
            iteration_num = i + 1
            iteration_events = []
            logger.info(f"[{submission_id}] >>> STARTING ITERATION {iteration_num}/{max_iters} <<<")
            
            def _log_event(evt_type: str, data: dict):
                evt = {"event": evt_type, "data": data}
                iteration_events.append(evt)
                return evt

            yield _log_event("iteration_start", {"iteration": iteration_num, "max": max_iters})

            # Check for cancellation signal
            await db.refresh(submission)
            if submission.is_cancelled:
                logger.warning(f"[{submission_id}] Repair CANCELLED by user.")
                yield {"event": "log_line", "data": {"msg": "🛑 REPAIR CANCELLED: Stopping loop and destroying sandbox."}}
                yield {"event": "complete", "data": {"status": "cancelled", "iterations": iteration_num}}
                return

            # 1. Run the code, capture errors
            exec_res = await sandbox.execute_code(container, code)
            raw_error = exec_res.get("error") or exec_res.get("output", "")
            
            # Filter out known infrastructure noise, TTY artifacts, and Tinker messages
            noise_patterns = [
                "boost:", "CommandNotFoundException", "sh: 1:", "tty", 
                "Aliasing", "ALREADY_LOADED", "TPD", "Rate limit"
            ]
            error_logs = "\n".join([
                line for line in raw_error.splitlines() 
                if not any(noise in line for noise in noise_patterns)
            ]).strip()

            # 1b. Classify error into structured category
            # SAFETY: If logs are very short after filtering (mostly noise), force 'NONE' classification
            if len(error_logs) < 200:
                from api.services.error_classifier import ClassifiedError
                classified_error = ClassifiedError(category="none", summary="Clear", details={}, full_trace="")
            else:
                classified_error = classify_error(error_logs)

            structured_error_for_llm = format_classified_error_for_llm(classified_error)
            
            # Stream the raw error to the frontend so it can display the live logs
            yield {"event": "error_detected", "data": {"logs": error_logs[:1000]}}
            yield {"event": "log_line", "data": {"msg": f"Error classified: {classified_error.category}"}}

            # --- SUCCESS EXIT: If code is correct (either initially or after a patch) ---
            if classified_error.category == "none":
                submission.status = "success"
                # Wait for any background writes to settle
                await asyncio.sleep(2)
                submission.final_code = await sandbox.read_file(container, class_info.dest_file) if 'class_info' in locals() else code
                
                # LEARNING: Store this success so it can be used for future repairs
                # Note: 'ai_resp' might be None if it was an Early Exit, store_repair_success handles this
                class MockResp: 
                    diagnosis = "Code verified healthy"
                    fix_description = "Initial code was correct or successfully patched"
                await context.store_repair_success(db, error_logs, locals().get('ai_resp', MockResp()), iteration_num)
                
                await db.commit()
                yield {"event": "log_line", "data": {"msg": "✨ Code verified as correct! Ending repair loop."}}
                yield {"event": "complete", "data": {"status": "success", "iterations": iteration_num}}
                return

            # 2. Gather context — parse structured JSON from boost_service
            # Use the full error logs for boost service, but pass structured version to LLM
            boost_ctx_raw = await boost_service.get_boost_context(container_id, error_logs, submission_id)
            try:
                boost_parsed = json.loads(boost_ctx_raw)
                boost_component_type = boost_parsed.get("component_type", "unknown")
                boost_schema = boost_parsed.get("schema_info", "")
                boost_ctx = boost_parsed.get("schema_info", "") + "\n" + "\n".join(boost_parsed.get("docs_excerpts", []))
            except (json.JSONDecodeError, AttributeError):
                boost_component_type = "unknown"
                boost_schema = ""
                boost_ctx = boost_ctx_raw
            yield {
                "event": "boost_queried",
                "data": {
                    "component_type": boost_component_type,
                    "context_text": boost_ctx[:500],  # trim for SSE
                    "schema": boost_schema[:300],
                }
            }

            signatures = await discovery.discover_referenced_signatures(container, code)
            if signatures:
                boost_ctx += f"\n\n## Referenced Class Signatures (Zoom-In)\n{signatures}"

            # Always inject the canonical target path so the AI never patches the wrong file
            boost_ctx = placement_hint + boost_ctx

            past_repairs = await context.get_similar_repairs(db, error_logs)
            yield {"event": "log_line", "data": {"msg": f"Context gathered — {boost_component_type} pattern detected"}}

            # 3. AI pipeline
            escalation_ctx = escalation_service.build_escalation_context(previous_attempts)
            yield {"event": "ai_thinking", "data": {"role": "Planning", "diagnosis": None}}
            
            # --- REPLAY MODE LOGIC ---
            replay_id = kwargs.get("replay_submission_id")
            if replay_id:
                logger.info(f"[{submission_id}] REPLAY MODE: Fetching stored response from {replay_id}")
                rep_res = await db.execute(
                    select(Iteration)
                    .where(Iteration.submission_id == replay_id, Iteration.iteration_num == iteration_num)
                    .limit(1)
                )
                rep_it = rep_res.scalars().first()
                if rep_it and rep_it.ai_response:
                    from api.services.ai_service import _parse_xml_response
                    ai_resp = _parse_xml_response(rep_it.ai_response)
                    models = {
                        "planner": rep_it.planner_model or "replay",
                        "executor": rep_it.executor_model or "replay",
                        "reviewer": rep_it.reviewer_model or "replay"
                    }
                else:
                    yield {"event": "error", "data": {"msg": f"Replay failed: No iteration {iteration_num} found for {replay_id}"}}
                    break
            else:
                # REAL AI CALL
                try:
                    ai_resp = None
                    models = {}
                    
                    yield _log_event("ai_thinking", {"status": "planning"})
                    async for evt_type, evt_data in pipeline.run_pipeline(
                        code, structured_error_for_llm, boost_ctx, previous_attempts, past_repairs, prompt, escalation_ctx, current_post_mortem, iteration_num=iteration_num
                    ):
                        event = _log_event(evt_type, evt_data)
                        
                        if evt_type == "final_result":
                            ai_resp, models = evt_data
                        else:
                            # Forward internal pipeline events to the SSE queue
                            yield event

                    if not ai_resp:
                        raise Exception("Pipeline failed to return final result")

                except Exception as pipeline_exc:
                    err_msg = str(pipeline_exc)
                    logger.error(f"[{submission_id}] Iteration {iteration_num} AI pipeline failed: {err_msg}")
                    yield _log_event("error", {"msg": f"AI pipeline failed: {err_msg}"})
                    db.add(Iteration(
                        submission_id=submission_id,
                        iteration_num=iteration_num,
                        code_input=code,
                        error_logs=error_logs + f"\n\n[SYSTEM] AI pipeline failed: {err_msg}",
                        ai_response=f'{{"error": "pipeline_failed"}}',
                        status="failed",
                        duration_ms=int((time.time() - start_time) * 1000),
                        pipeline_logs=json.dumps(iteration_events),
                    ))
                    await db.commit()
                    previous_attempts.append({
                        "diagnosis": "Pipeline Failure",
                        "outcome": "failed",
                        "failure_reason": "pipeline_error",
                        "failure_details": err_msg[:200],
                        "action": "execute_plan",
                    })
                    continue

            if not ai_resp.patches:
                yield _log_event("error", {"msg": "AI returned zero patches. Escalating."})
                await escalation_service.escalate_empty_patch(submission_id, iteration_num, ai_resp.raw)
                db.add(Iteration(
                    submission_id=submission_id,
                    iteration_num=iteration_num,
                    code_input=code,
                    error_logs=error_logs + "\n\n[SYSTEM] AI returned zero patches.",
                    ai_response=ai_resp.raw,
                    planner_model=models.get("planner"),
                    executor_model=models.get("executor"),
                    reviewer_model=models.get("reviewer"),
                    status="failed",
                    duration_ms=int((time.time() - start_time) * 1000),
                    pipeline_logs=json.dumps(iteration_events),
                ))
                await db.commit()
                previous_attempts.append({
                    "diagnosis": ai_resp.diagnosis,
                    "outcome": "failed",
                    "failure_reason": "pipeline_error",
                    "failure_details": "AI returned zero patches.",
                    "action": "execute_plan",
                })
                continue

            yield _log_event("ai_thinking", {"diagnosis": ai_resp.diagnosis, "fix_description": ""})

            # 4. Apply patches
            logger.info(f"[{submission_id}] Applying {len(ai_resp.patches)} patches to sandbox...")
            
            # SAFETY: Aggressively strip PHP closing tags and markdown code blocks
            for p in ai_resp.patches:
                if p.replacement:
                    p.replacement = p.replacement.replace("?>", "")
                    p.replacement = p.replacement.replace("```php", "")
                    p.replacement = p.replacement.replace("```", "")
                    p.replacement = p.replacement.strip()

            try:
                apply_res = await patch_service.apply_all(container_id, ai_resp.patches)
                success_count = sum(1 for v in apply_res.values() if v)
                fail_count = len(apply_res) - success_count
                logger.info(f"[{submission_id}] Patches applied: {success_count} success, {fail_count} failed.")
            except patch_service.PatchApplicationError as pae:
                # Every patch failed (lint error, forbidden path, etc.) — record and continue
                logger.error(f"[{submission_id}] {pae}")
                yield _log_event("patch_skipped", {"reason": str(pae)})
                db.add(Iteration(
                    submission_id=submission_id,
                    iteration_num=iteration_num,
                    code_input=code,
                    error_logs=error_logs + f"\n\n[PATCH FAILED] {pae}",
                    ai_response=ai_resp.raw,
                    planner_model=models.get("planner"),
                    executor_model=models.get("executor"),
                    reviewer_model=models.get("reviewer"),
                    status="failed",
                    failure_reason="patch_failed",
                    failure_details=str(pae)[:500],
                    boost_context=boost_ctx[:2000] if boost_ctx else None,
                    duration_ms=int((time.time() - start_time) * 1000),
                    pipeline_logs=json.dumps(iteration_events),
                ))
                previous_attempts.append({
                    "diagnosis": ai_resp.diagnosis,
                    "outcome": "failed",
                    "files": list(created_files),
                    "failure_reason": "patch_failed",
                    "failure_details": str(pae)[:200],
                    "fix_description": ai_resp.fix_description,
                    "action": "execute_plan",
                    "reviewer_evidence": ai_resp.reviewer_evidence if hasattr(ai_resp, 'reviewer_evidence') else None,
                })
                await db.commit()
                yield _log_event("iteration_complete", {"num": iteration_num, "success": False})
                continue

            for path, ok in apply_res.items():
                if ok:
                    created_files.add(path)
                    yield _log_event("patch_applied", {"path": path, "action": "full_replace"})
                else:
                    yield _log_event("patch_skipped", {"path": path})

            if not any(apply_res.values()):
                yield _log_event("error", {"msg": "All patches failed to apply."})
                break

            # ── Fix: remove original /submitted/code.php so execute_code in the next
            # iteration does NOT re-require the un-patched class and cause
            # "Cannot declare class X, already in use" fatal errors.
            from api.services.sandbox import docker as _docker
            _container = sandbox.get_container(container_id)
            await _docker.execute(_container, "rm -f /submitted/code.php", timeout=3)

            # Build compact patch summary for DB
            patch_summary = json.dumps([
                {"action": p.action, "path": p.target, "ok": apply_res.get(p.target or p.filename, False)}
                for p in ai_resp.patches
            ])

            # 5. Static analysis gate
            for path in (p for p, ok in apply_res.items() if ok and p.endswith(".php")):
                stan_res = await sandbox.run_phpstan(container, path)
                yield _log_event("phpstan_result", {
                    "path": path,
                    "success": stan_res["success"],
                    "output": stan_res["output"]
                })
                if not stan_res["success"]:
                    error_logs += f"\n\nPHPSTAN ({path}):\n{stan_res['output']}"

            # 6. Pest tests
            # SAFETY: Aggressively strip PHP closing tags, markdown blocks, and whitespace
            cleaned_pest = ai_resp.pest_test.replace("?>", "")
            cleaned_pest = cleaned_pest.replace("```php", "")
            cleaned_pest = cleaned_pest.replace("```", "")
            cleaned_pest = cleaned_pest.strip()
            pest_code = sandbox.prepare_pest_test(cleaned_pest, class_info.fqcn)
            
            # 6a. Pre-flight validation: Check Pest test syntax before running
            # Write to temporary file and lint
            await sandbox.write_file(container, "/tmp/pest_preflight.php", pest_code)
            lint_ok, lint_msg = await sandbox.lint_php(container, "/tmp/pest_preflight.php")
            if not lint_ok:
                failure_reason = "test_syntax_error"
                failure_details = f"Pest test has syntax errors: {lint_msg}"
                error_logs += f"\n\nPEST SYNTAX ERROR:\n{lint_msg}"
                
                # Try to get post-mortem for test failure
                try:
                    pm_res = await ai_service.get_post_mortem(
                        code,
                        [{"action": p.action, "path": p.target} for p in ai_resp.patches],
                        f"Generated Pest test has syntax errors:\n{lint_msg}",
                        await sandbox.capture_laravel_log(container),
                        boost_ctx,
                        failure_reason="syntax_error"
                    )
                    pm_category = pm_res.category
                    pm_strategy = pm_res.strategy
                    current_post_mortem = f"Analysis: {pm_res.analysis}\nStrategy: {pm_res.strategy}"
                except Exception as pm_exc:
                    logger.warning(f"[{submission_id}] PostMortem skipped for test syntax error: {pm_exc}")
                    pm_category = "test"
                    pm_strategy = "Executor must generate syntactically valid Pest test code"
                
                # Record and skip to next iteration
                db.add(Iteration(
                    submission_id=submission_id,
                    iteration_num=iteration_num,
                    code_input=code,
                    error_logs=error_logs,
                    ai_response=ai_resp.raw,
                    patch_applied=patch_summary,
                    pest_test_code=pest_code,
                    planner_model=models.get("planner"),
                    executor_model=models.get("executor"),
                    reviewer_model=models.get("reviewer"),
                    mutation_score=None,
                    boost_context=boost_ctx[:2000] if boost_ctx else None,
                    status="failed",
                    duration_ms=int((time.time() - start_time) * 1000),
                    failure_reason=failure_reason,
                    failure_details=failure_details,
                    pm_category=pm_category,
                    pm_strategy=pm_strategy,
                    pipeline_logs=json.dumps(iteration_events),
                ))
                
                previous_attempts.append({
                    "diagnosis": ai_resp.diagnosis,
                    "outcome": "failed",
                    "files": list(created_files),
                    "failure_reason": failure_reason,
                    "failure_details": failure_details,
                    "pm_category": pm_category,
                    "pm_strategy": pm_strategy,
                    "fix_description": ai_resp.fix_description,
                    "action": "execute_plan",
                    "reviewer_evidence": ai_resp.reviewer_evidence if hasattr(ai_resp, 'reviewer_evidence') else None,
                })
                
                yield _log_event("iteration_complete", {"num": iteration_num, "success": False})
                await db.commit()
                continue
            
            yield _log_event("log_line", {"msg": "Running Pest functional tests..."})
            pest_res = await sandbox.run_pest_test(container, pest_code)
            if not pest_res["success"]:
                error_logs += f"\n\nPEST TEST FAILURE:\n{pest_res['output']}"
                laravel_log = await sandbox.capture_laravel_log(container)
                error_logs += f"\n\nLARAVEL LOG:\n{laravel_log}"
            
            yield _log_event("pest_result", {
                "status": "pass" if pest_res["success"] else "fail",
                "output": pest_res.get("output", ""),
                "duration_ms": int((time.time() - start_time) * 1000),
            })

            current_post_mortem = ""
            pm_category = None
            pm_strategy = None
            failure_reason = None
            failure_details = None

            # 6b. Post-Mortem analysis if Pest failed (non-fatal)
            if not pest_res["success"]:
                failure_reason = "pest_failed"
                failure_details = pest_res.get("output", "")[:500]  # Capture first 500 chars of failure
                try:
                    pm_res = await ai_service.get_post_mortem(
                        code,
                        [{"action": p.action, "path": p.target} for p in ai_resp.patches],
                        pest_res["output"],
                        await sandbox.capture_laravel_log(container),
                        boost_ctx,
                        failure_reason="pest_failed"
                    )
                    current_post_mortem = f"Analysis: {pm_res.analysis}\nStrategy: {pm_res.strategy}"
                    pm_category = pm_res.category
                    pm_strategy = pm_res.strategy
                    yield _log_event("log_line", {"msg": f"Critic Analysis: {pm_res.category}"})
                except Exception as pm_exc:
                    logger.warning(f"[{submission_id}] PostMortem skipped (non-fatal): {pm_exc}")
                    current_post_mortem = ""

            # 7. Mutation gate
            mutation_score = None
            if pest_res["success"] and kwargs.get("use_mutation_gate", True):
                yield _log_event("log_line", {"msg": "Pest passed. Running Mutation Gate analysis..."})
                mutation_res = await sandbox.run_mutation_test(container)
                mutation_score = mutation_res.score
                if not mutation_res.passed:
                    failure_reason = "mutation_failed"
                    failure_details = f"Score: {mutation_score}%"
                    error_logs += f"\n\nMUTATION GATE FAILURE (Score: {mutation_score}%):\n{mutation_res.output}"

                    try:
                        pm_res = await ai_service.get_post_mortem(
                            code,
                            [{"action": p.action, "path": p.target} for p in ai_resp.patches],
                            f"Mutation Gate Failed with score {mutation_score}%.\n{mutation_res.output}",
                            await sandbox.capture_laravel_log(container),
                            boost_ctx,
                            failure_reason="mutation_failed"
                        )
                        current_post_mortem = f"Analysis: {pm_res.analysis}\nStrategy: {pm_res.strategy}"
                        pm_category = pm_res.category
                        pm_strategy = pm_res.strategy
                        yield _log_event("log_line", {"msg": f"Critic Analysis (Mutation): {pm_res.category}"})
                    except Exception as pm_exc:
                        logger.warning(f"[{submission_id}] Mutation PostMortem skipped (non-fatal): {pm_exc}")

                yield _log_event("mutation_result", {
                    "score": mutation_score,
                    "passed": mutation_res.passed,
                    "duration_ms": int((time.time() - start_time) * 1000),
                })

            # 8. Evaluate outcome
            success = pest_res["success"] and (
                mutation_score is None or mutation_score >= settings.mutation_score_threshold
            )
            it_status = "success" if success else "failed"

            try:
                if it_status == "failed" and classified_error.category == "unknown":
                    logger.warning(f"[{submission_id}] Iteration {iteration_num} failed with UNKNOWN error. Raw logs head: {str(error_logs)[:200]}")

                logger.info(
                    f"[{submission_id}] ITERATION {iteration_num} SUMMARY: "
                    f"Status: {it_status} | "
                    f"Pest: {'PASS' if pest_res['success'] else 'FAIL'} | "
                    f"Mutation: {mutation_score if mutation_score is not None else 'N/A'}% | "
                    f"Models: {json.dumps(models)}"
                )
                db.add(Iteration(
                    submission_id=submission_id,
                    iteration_num=iteration_num,
                    code_input=code,
                    error_logs=error_logs,
                    ai_response=ai_resp.raw,
                    patch_applied=patch_summary,
                    pest_test_code=pest_code,
                    pest_test_result=pest_res.get("output", "")[:2000],
                    planner_model=models.get("planner"),
                    executor_model=models.get("executor"),
                    reviewer_model=models.get("reviewer"),
                    mutation_score=mutation_score,
                    boost_context=boost_ctx[:2000] if boost_ctx else None,
                    status=it_status,
                    duration_ms=int((time.time() - start_time) * 1000),
                    failure_reason=failure_reason,
                    failure_details=failure_details,
                    pm_category=pm_category,
                    pm_strategy=pm_strategy,
                    pipeline_logs=json.dumps(iteration_events),
                ))

                previous_attempts.append({
                    "diagnosis": ai_resp.diagnosis,
                    "outcome": it_status,
                    "files": list(created_files),
                    "failure_reason": failure_reason,
                    "failure_details": failure_details,
                    "pm_category": pm_category,
                    "pm_strategy": pm_strategy,
                    "fix_description": ai_resp.fix_description,
                    "action": "execute_plan",
                    "reviewer_evidence": ai_resp.reviewer_evidence if hasattr(ai_resp, 'reviewer_evidence') else None,
                })

                yield _log_event("iteration_complete", {"num": iteration_num, "success": success})

                if success:
                    submission.status = "success"
                    if primary_target_file:
                        submission.final_code = await sandbox.read_file(container, primary_target_file)
                    elif ai_resp.patches:
                        submission.final_code = await sandbox.read_file(container, ai_resp.patches[0].target)
                    else:
                        submission.final_code = code
                    await context.store_repair_success(db, error_logs, ai_resp, iteration_num)
                    await db.commit()
                    yield _log_event("log_line", {"msg": "✅ JOB DONE: Success! All tests passed and mutation gate satisfied."})
                    yield _log_event("complete", {"status": "success", "iterations": iteration_num, "mutation_score": mutation_score})
                    return

                await db.commit()

            except Exception as e:
                await db.rollback()
                logger.error(f"[{submission_id}] DB write failed on iteration {iteration_num}: {e}")
                raise

        # Loop exhausted — mark failed
        try:
            submission.status = "failed"
            await db.commit()
        except Exception:
            await db.rollback()
        yield {"event": "log_line", "data": {"msg": "❌ JOB DONE: Failed. Max iterations reached without a stable fix."}}
        yield {"event": "complete", "data": {"status": "failed", "iterations": max_iters, "mutation_score": None}}

    except Exception as e:
        await db.rollback()
        await db.refresh(submission)
        
        if submission.is_cancelled:
            logger.info(f"[{submission_id}] Orchestrator caught termination of cancelled job.")
            yield {"event": "complete", "data": {"status": "cancelled", "iterations": locals().get('iteration_num', 0)}}
        else:
            logger.exception(f"[{submission_id}] Fatal error: {e}")
            try:
                submission.status = "failed"
                submission.error_summary = str(e)
                await db.commit()
            except Exception:
                pass
            yield {"event": "error", "data": {"msg": str(e)}}
            yield {"event": "complete", "data": {"status": "failed", "iterations": locals().get('iteration_num', 0)}}
    finally:
        # 1. Kill the container if it exists
        if 'container_id' in locals():
            await sandbox.destroy_sandbox(container_id)
        
        # 2. Hard cleanup of SSE state (to avoid memory leaks on fatal crash)
        from api.routers.repair import _event_queues, _repair_done
        _repair_done[submission_id] = True
        # Note: we don't pop the queue here, let the stream_repair generator handle it 
        # so it can finish flushing to the client.
