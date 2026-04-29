
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

    previous_attempts: list[dict] = []
    created_files: set[str] = set()
    container_id = await sandbox.create_sandbox()

    try:
        yield {"type": "info", "message": "Sandbox ready", "id": container_id}
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

        yield {"type": "info", "message": f"Class detected: {class_info.fqcn}"}

        # ── Repair loop ───────────────────────────────────────────────────────
        max_iters = kwargs.get("max_iterations") or settings.max_iterations
        for i in range(max_iters):
            start_time = time.time()
            iteration_num = i + 1
            yield {"type": "iteration_start", "num": iteration_num}

            # 1. Run the code, capture errors
            exec_res = await sandbox.execute_code(container, code)
            raw_error = exec_res.get("error") or exec_res.get("output", "")
            
            # Filter out known infrastructure noise
            error_logs = "\n".join([
                line for line in raw_error.splitlines() 
                if "boost:" not in line and "CommandNotFoundException" not in line
            ])

            # 2. Gather context
            boost_ctx = await boost_service.get_boost_context(container_id, error_logs, submission_id)
            signatures = await discovery.discover_referenced_signatures(container, code)
            if signatures:
                boost_ctx += f"\n\n## Referenced Class Signatures (Zoom-In)\n{signatures}"
            
            past_repairs = await context.get_similar_repairs(db, error_logs)
            yield {"type": "context_gathered", "error": error_logs[:200]}

            # 3. AI pipeline
            escalation_ctx = escalation_service.build_escalation_context(previous_attempts)
            try:
                ai_resp, models = await asyncio.wait_for(
                    pipeline.run_pipeline(
                        code, error_logs, boost_ctx, previous_attempts, past_repairs, prompt, escalation_ctx, current_post_mortem
                    ),
                    timeout=180.0
                )
            except asyncio.TimeoutError:
                logger.error(f"[{submission_id}] Iteration {iteration_num} timed out during AI pipeline.")
                yield {"type": "error", "message": "AI pipeline timed out after 3 minutes."}
                
                db.add(Iteration(
                    submission_id=submission_id,
                    iteration_num=iteration_num,
                    code_input=code,
                    error_logs=error_logs + "\n\n[SYSTEM] AI pipeline timed out.",
                    ai_response='{"error": "timeout"}',
                    status="failed",
                    duration_ms=int((time.time() - start_time) * 1000),
                ))
                await db.commit()
                continue

            if not ai_resp.patches:
                yield {"type": "error", "message": "AI returned zero patches. Escalating."}
                await escalation_service.escalate_empty_patch(submission_id, iteration_num, ai_resp.raw)
                break

            yield {"type": "ai_thinking", "diagnosis": ai_resp.diagnosis}

            # 4. Apply patches
            apply_res = await patch_service.apply_all(container_id, ai_resp.patches)
            for path, ok in apply_res.items():
                if ok:
                    created_files.add(path)
                    yield {"type": "patch_applied", "path": path}
                else:
                    yield {"type": "patch_skipped", "path": path}

            if not any(apply_res.values()):
                yield {"type": "error", "message": "All patches failed to apply."}
                break

            # 5. Static analysis gate
            for path in (p for p, ok in apply_res.items() if ok and p.endswith(".php")):
                stan_res = await sandbox.run_phpstan(container, path)
                if not stan_res["success"]:
                    error_logs += f"\n\nPHPSTAN ({path}):\n{stan_res['output']}"

            # 6. Pest tests
            pest_code = sandbox.prepare_pest_test(ai_resp.pest_test, class_info.fqcn)
            pest_res = await sandbox.run_pest_test(container, pest_code)
            if not pest_res["success"]:
                error_logs += f"\n\nPEST TEST FAILURE:\n{pest_res['output']}"
                laravel_log = await sandbox.capture_laravel_log(container)
                error_logs += f"\n\nLARAVEL LOG:\n{laravel_log}"
            yield {"type": "pest_result", "success": pest_res["success"]}

            current_post_mortem = ""

            # 6b. Post-Mortem analysis if Pest failed (non-fatal — loop continues if this fails)
            if not pest_res["success"]:
                try:
                    pm_res = await ai_service.get_post_mortem(
                        code,
                        [{"action": p.action, "path": p.target} for p in ai_resp.patches],
                        pest_res["output"],
                        await sandbox.capture_laravel_log(container),
                        boost_ctx
                    )
                    current_post_mortem = f"Analysis: {pm_res.analysis}\nStrategy: {pm_res.strategy}"
                    yield {"type": "info", "message": f"Critic Analysis: {pm_res.category}"}
                except Exception as pm_exc:
                    logger.warning(f"[{submission_id}] PostMortem skipped (non-fatal): {pm_exc}")
                    current_post_mortem = ""  # next iteration will plan without post-mortem context

            # 7. Mutation gate
            mutation_score = None
            if pest_res["success"] and kwargs.get("use_mutation_gate", True):
                mutation_res = await sandbox.run_mutation_test(container)
                mutation_score = mutation_res.score
                if not mutation_res.passed:
                    error_logs += f"\n\nMUTATION GATE FAILURE (Score: {mutation_score}%):\n{mutation_res.output}"

                    # 7b. Post-Mortem analysis for Mutation failure (non-fatal)
                    try:
                        pm_res = await ai_service.get_post_mortem(
                            code,
                            [{"action": p.action, "path": p.target} for p in ai_resp.patches],
                            f"Mutation Gate Failed with score {mutation_score}%.\n{mutation_res.output}",
                            await sandbox.capture_laravel_log(container),
                            boost_ctx
                        )
                        current_post_mortem = f"Analysis: {pm_res.analysis}\nStrategy: {pm_res.strategy}"
                        yield {"type": "info", "message": f"Critic Analysis (Mutation): {pm_res.category}"}
                    except Exception as pm_exc:
                        logger.warning(f"[{submission_id}] Mutation PostMortem skipped (non-fatal): {pm_exc}")

                yield {"type": "mutation_result", "score": mutation_score, "success": mutation_res.passed}

            # 8. Evaluate outcome
            success = pest_res["success"] and (
                mutation_score is None or mutation_score >= settings.mutation_score_threshold
            )
            it_status = "success" if success else "failed"

            try:
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
                    status=it_status,
                    duration_ms=int((time.time() - start_time) * 1000),
                ))

                previous_attempts.append({
                    "diagnosis": ai_resp.diagnosis,
                    "outcome": it_status,
                    "files": list(created_files),
                })

                yield {"type": "iteration_complete", "num": iteration_num, "success": success}

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
                    yield {"type": "repair_success"}
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
        yield {"type": "repair_failed"}

    except Exception as e:
        await db.rollback()
        logger.exception(f"[{submission_id}] Fatal error: {e}")
        try:
            submission.status = "failed"
            submission.error_summary = str(e)
            await db.commit()
        except Exception:
            pass
        yield {"type": "error", "message": str(e)}
    finally:
        await sandbox.destroy_sandbox(container_id)
