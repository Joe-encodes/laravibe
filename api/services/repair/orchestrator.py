
import asyncio
import json
import logging
import time
from typing import AsyncGenerator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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


def _safe_json_dumps(obj) -> str:
    from dataclasses import is_dataclass, asdict
    class _Fallback(json.JSONEncoder):
        def default(self, o):
            if "mock" in type(o).__name__.lower():
                return f"<Mock id={id(o)}>"
            if is_dataclass(o): return asdict(o)
            if hasattr(o, "__dict__"): return o.__dict__
            try: return super().default(o)
            except TypeError: return str(o)
    return json.dumps(obj, cls=_Fallback, ensure_ascii=False)


async def run_repair_loop(
    submission_id: str,
    code: str,
    prompt: str | None = None,
    db: AsyncSession | None = None,
    **kwargs,
) -> AsyncGenerator[dict, None]:
    """Orchestrate one full repair lifecycle: sandbox → AI loop → persist results."""
    set_submission_id(submission_id)

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def get_session():
        if db is not None:
            yield db
        else:
            from api.database import AsyncSessionLocal
            async with AsyncSessionLocal() as session:
                yield session

    async with get_session() as session:
        submission = (
            await session.execute(select(Submission).where(Submission.id == submission_id))
        ).scalar_one()
        submission.status = "running"
        await session.commit()

    # 0. Pre-flight Docker Check
    try:
        from api.services.sandbox import docker as _docker
        _docker._get_client().ping()
    except Exception as d_exc:
        logger.error(f"[{submission_id}] Docker engine unreachable: {d_exc}")
        yield {"event": "error", "data": {"msg": "Critical Error: Docker engine is unreachable."}}
        async with get_session() as session:
            submission = (
                await session.execute(select(Submission).where(Submission.id == submission_id))
            ).scalar_one()
            submission.status = "failed"
            submission.error_summary = "Docker engine unreachable"
            await session.commit()
        return

    previous_attempts: list[dict] = []
    created_files: set[str] = set()

    try:
        container_id = await sandbox.create_sandbox()
        async with get_session() as session:
            submission = (
                await session.execute(select(Submission).where(Submission.id == submission_id))
            ).scalar_one()
            submission.container_id = container_id
            await session.commit()
    except Exception as c_exc:
        logger.error(f"[{submission_id}] Failed to create sandbox: {c_exc}")
        yield {"event": "error", "data": {"msg": f"Failed to create sandbox: {c_exc}"}}
        async with get_session() as session:
            submission = (
                await session.execute(select(Submission).where(Submission.id == submission_id))
            ).scalar_one()
            submission.status = "failed"
            submission.error_summary = f"Sandbox creation failed: {c_exc}"
            await session.commit()
        return

    try:
        yield {"event": "log_line", "data": {"msg": f"Sandbox created: {container_id[:12]}...", "id": container_id}}
        container = sandbox.get_container(container_id)

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
        last_pest_code = ""  # Track AI-generated test across iterations

        _rel_dest = class_info.dest_file.replace("/var/www/sandbox/", "")
        placement_hint = (
            f"\n\n## ⚠️  CRITICAL — Correct patch target\n"
            f"The class `{class_info.fqcn}` lives at `{_rel_dest}` inside the Laravel project.\n"
            f"ALL `<file>` patches MUST target `{_rel_dest}`. "
            f"NEVER patch `tests/fixtures/` paths — those are read-only source files.\n"
        )

        yield {"event": "log_line", "data": {"msg": f"Class detected: {class_info.fqcn} → {_rel_dest}"}}

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

            async with get_session() as session:
                submission_obj = (
                    await session.execute(select(Submission).where(Submission.id == submission_id))
                ).scalar_one()
                await session.refresh(submission_obj)
                is_cancelled = submission_obj.is_cancelled
            if is_cancelled:
                logger.warning(f"[{submission_id}] Repair CANCELLED by user.")
                yield {"event": "log_line", "data": {"msg": "🛑 REPAIR CANCELLED."}}
                yield {"event": "complete", "data": {"status": "cancelled", "iterations": iteration_num}}
                return

            # ── 1. Run code, capture errors ───────────────────────────────────
            exec_res = await sandbox.execute_code(container, code)
            raw_error = exec_res.get("error") or exec_res.get("output", "")

            noise_patterns = ["boost:", "CommandNotFoundException", "sh: 1:", "tty", "Aliasing", "ALREADY_LOADED", "TPD", "Rate limit"]
            error_logs = "\n".join([
                line for line in raw_error.splitlines()
                if not any(noise in line for noise in noise_patterns)
            ]).strip()

            is_infra_error = any(x in error_logs for x in ["[TIMEOUT]", "[CRASH]", "[SYSTEM_ERROR]", "[CANCELLED]"])
            if is_infra_error:
                yield _log_event("error", {"msg": f"Infrastructure failure: {error_logs}"})
                break

            if len(error_logs) < 10:
                # Only skip AI repair if there is genuinely zero output (no error at all)
                from api.services.error_classifier import ClassifiedError
                classified_error = ClassifiedError(category="none", summary="Clear", details={}, full_trace="")
            else:
                classified_error = classify_error(error_logs)

            structured_error_for_llm = format_classified_error_for_llm(classified_error)
            yield _log_event("error_detected", {"logs": error_logs[:1000]})
            yield _log_event("log_line", {"msg": f"Error classified: {classified_error.category}"})

            # Shared state for this iteration
            ai_resp = None
            models = {}
            pest_code = ""
            pest_res = {"success": False, "output": ""}
            patch_summary = ""
            boost_ctx = ""
            boost_component_type = "unknown"
            plan_to_use = None

            compilation_clean = (classified_error.category == "none")
            # Force AI repair if: compile error, prior pest/mutation failure, or no test code yet
            had_prior_failure = bool(previous_attempts) and previous_attempts[-1].get(
                "outcome"
            ) == "failed"
            needs_ai_repair = not compilation_clean or had_prior_failure or not last_pest_code


            # ── PATH A: AI repair needed (compile error OR prior pest/mutation failure) ──
            if needs_ai_repair:
                boost_ctx_raw = await boost_service.get_boost_context(container_id, error_logs, submission_id)
                try:
                    boost_parsed = json.loads(boost_ctx_raw)
                    boost_component_type = boost_parsed.get("component_type", "unknown")
                    boost_schema = boost_parsed.get("schema_info", "")
                    boost_ctx = boost_parsed.get("schema_info", "") + "\n" + "\n".join(boost_parsed.get("docs_excerpts", []))
                except (json.JSONDecodeError, AttributeError):
                    boost_ctx = boost_ctx_raw

                yield _log_event("boost_queried", {"component_type": boost_component_type, "context_text": boost_ctx[:500]})

                signatures = await discovery.discover_referenced_signatures(container, code)
                if signatures:
                    boost_ctx += f"\n\n## Referenced Class Signatures (Zoom-In)\n{signatures}"
                boost_ctx = placement_hint + boost_ctx

                async with get_session() as session:
                    past_repairs = await context.get_similar_repairs(session, error_logs)
                yield {"event": "log_line", "data": {"msg": f"Context gathered — {boost_component_type} pattern detected"}}

                escalation_ctx = escalation_service.build_escalation_context(previous_attempts)
                yield {"event": "ai_thinking", "data": {"role": "Planning", "diagnosis": None}}

                try:
                    yield _log_event("ai_thinking", {"status": "running_pipeline"})
                    t_start = time.monotonic()
                    async for evt_type, evt_data in pipeline.run_pipeline(
                        code, structured_error_for_llm, boost_ctx, previous_attempts,
                        past_repairs, prompt, escalation_ctx, current_post_mortem,
                        iteration_num=iteration_num, max_iters=max_iters
                    ):
                        if evt_type == "final_result":
                            ai_resp, models = evt_data
                        elif evt_type == "approved_plan":
                            plan_to_use = evt_data
                        else:
                            yield _log_event(evt_type, evt_data)
                    logger.info(f"[{submission_id}] AI Pipeline completed in {int((time.monotonic() - t_start)*1000)}ms")
                    if not ai_resp:
                        raise Exception("Pipeline failed to return final result")
                except Exception as pipeline_exc:
                    err_msg = str(pipeline_exc)
                    logger.error(f"[{submission_id}] Iter {iteration_num} AI pipeline failed: {err_msg}")
                    yield _log_event("error", {"msg": f"AI pipeline failed: {err_msg}"})
                    async with get_session() as session:
                        session.add(Iteration(
                            submission_id=submission_id, iteration_num=iteration_num, code_input=code,
                            error_logs=error_logs + f"\n\n[SYSTEM] AI pipeline failed: {err_msg}",
                            ai_response='{"error": "pipeline_failed"}', status="failed",
                            duration_ms=int((time.time() - start_time) * 1000),
                            pipeline_logs=_safe_json_dumps(iteration_events),
                        ))
                        submission_obj = (
                            await session.execute(select(Submission).where(Submission.id == submission_id))
                        ).scalar_one()
                        submission_obj.total_iterations = iteration_num
                        await session.commit()
                    previous_attempts.append({"diagnosis": "Pipeline Failure", "outcome": "failed",
                                              "failure_reason": "pipeline_error", "action": "execute_plan"})
                    yield _log_event("iteration_complete", {"num": iteration_num, "success": False})
                    continue

                is_aborted = ai_resp and "aborted" in str(ai_resp.thought_process).lower()
                is_mutation_gap = bool(previous_attempts and previous_attempts[-1].get("failure_reason") == "mutation_failed")
                if not ai_resp or (not ai_resp.patches and not is_mutation_gap) or is_aborted:
                    msg = "AI returned zero patches."
                    failure_reason = "pipeline_error"
                    if is_aborted:
                        msg = f"🛑 [ABORTED] The pipeline has terminated the run early: {ai_resp.diagnosis}"
                        failure_reason = "aborted"
                    yield _log_event("error", {"msg": msg})
                    async with get_session() as session:
                        session.add(Iteration(
                            submission_id=submission_id, iteration_num=iteration_num, code_input=code,
                            error_logs=error_logs + f"\n\n[SYSTEM] {msg}",
                            ai_response=ai_resp.raw if ai_resp else "", status="failed",
                            duration_ms=int((time.time() - start_time) * 1000),
                            pipeline_logs=_safe_json_dumps(iteration_events),
                            failure_reason=failure_reason,
                        ))
                        submission_obj = (
                            await session.execute(select(Submission).where(Submission.id == submission_id))
                        ).scalar_one()
                        submission_obj.total_iterations = iteration_num
                        submission_obj.status = "failed"
                        submission_obj.error_summary = msg
                        await session.commit()
                    if is_aborted:
                        break
                    previous_attempts.append({"diagnosis": ai_resp.diagnosis if ai_resp else "N/A",
                                               "outcome": "failed", "failure_reason": "pipeline_error",
                                               "action": "execute_plan"})
                    continue

                yield _log_event("ai_thinking", {"diagnosis": ai_resp.diagnosis, "fix_description": ""})
                logger.info(f"[{submission_id}] Applying {len(ai_resp.patches)} patches...")

                for p in ai_resp.patches:
                    if p.replacement:
                        p.replacement = p.replacement.replace("?>", "").replace("```php", "").replace("```", "").strip()

                try:
                    apply_res = await patch_service.apply_all(container_id, ai_resp.patches) if ai_resp.patches else {}
                    logger.info(f"[{submission_id}] Patches: {sum(v for v in apply_res.values())} ok, {sum(not v for v in apply_res.values())} failed.")
                except patch_service.PatchApplicationError as pae:
                    logger.error(f"[{submission_id}] {pae}")
                    yield _log_event("patch_skipped", {"reason": str(pae)})
                    async with get_session() as session:
                        session.add(Iteration(
                            submission_id=submission_id, iteration_num=iteration_num, code_input=code,
                            error_logs=error_logs + f"\n\n[PATCH FAILED] {pae}", ai_response=ai_resp.raw,
                            status="failed", failure_reason="patch_failed", failure_details=str(pae)[:500],
                            duration_ms=int((time.time() - start_time) * 1000),
                            pipeline_logs=_safe_json_dumps(iteration_events),
                        ))
                        await session.commit()
                    previous_attempts.append({"diagnosis": ai_resp.diagnosis, "outcome": "failed",
                                              "failure_reason": "patch_failed", "action": "execute_plan"})
                    yield _log_event("iteration_complete", {"num": iteration_num, "success": False})
                    continue

                for path, ok in apply_res.items():
                    if ok:
                        created_files.add(path)
                        yield _log_event("patch_applied", {"path": path, "action": "full_replace"})
                    else:
                        yield _log_event("patch_skipped", {"path": path})

                if ai_resp.patches and not any(apply_res.values()):
                    yield _log_event("error", {"msg": "All patches failed to apply."})
                    break

                # Run database migrations if any successfully applied patch is a migration
                logger.info(f"[{submission_id}] Debugging has_migration. apply_res keys: {list(apply_res.keys())}")
                for p in ai_resp.patches:
                    logger.info(f"[{submission_id}] Debugging has_migration. Patch filename: {p.filename} target: {p.target}")
                has_migration = False
                for p in ai_resp.patches:
                    filename = p.filename or p.target
                    if filename and apply_res.get(filename, False):
                        if "migrations/" in filename:
                            has_migration = True
                            break
                if has_migration:
                    # Clean up obsolete migrations from previous iterations to avoid execution errors
                    current_applied_paths = {path for path, ok in apply_res.items() if ok}
                    to_delete = []
                    for f in list(created_files):
                        if "migrations/" in f and f not in current_applied_paths:
                            to_delete.append(f)
                    
                    from api.services.sandbox import docker as _docker_mig
                    for f in to_delete:
                        logger.info(f"[{submission_id}] Cleaning up obsolete migration from prior iteration: {f}")
                        await _docker_mig.execute(sandbox.get_container(container_id), f"rm -f /var/www/sandbox/{f}", timeout=5)
                        created_files.discard(f)

                    yield _log_event("log_line", {"msg": "Database migration detected. Running php artisan migrate:fresh..."})
                    migrate_res = await _docker_mig.execute(sandbox.get_container(container_id), "php /var/www/sandbox/artisan migrate:fresh --force", timeout=20)
                    logger.info(f"[{submission_id}] Migration stdout: {migrate_res.stdout} stderr: {migrate_res.stderr}")
                    yield _log_event("log_line", {"msg": f"Migration completed with exit code {migrate_res.exit_code}"})
                    # Bust the Boost context cache so the next iteration sees the updated schema
                    boost_service._cache.clear()
                    logger.info(f"[{submission_id}] Boost context cache cleared after migration.")

                from api.services.sandbox import docker as _docker2
                await _docker2.execute(sandbox.get_container(container_id), "rm -f /submitted/code.php", timeout=3)

                patch_summary = json.dumps([
                    {"action": p.action, "path": p.target, "ok": apply_res.get(p.target or p.filename, False)}
                    for p in ai_resp.patches
                ])

                # PHPStan gate
                phpstan_failed = False
                for path in (p for p, ok in apply_res.items() if ok and p.endswith(".php")):
                    stan_res = await sandbox.run_phpstan(container, path)
                    logger.info(f"[{submission_id}] PHPStan ({path}): {'OK' if stan_res['success'] else 'FAIL'}")
                    yield _log_event("phpstan_result", {"path": path, "success": stan_res["success"], "output": stan_res["output"]})
                    if not stan_res["success"]:
                        error_logs += f"\n\nPHPSTAN ({path}):\n{stan_res['output']}"
                        phpstan_failed = True
                
                if phpstan_failed:
                    logger.warning(f"[{submission_id}] PHPStan failed — skipping Pest and looping to next iteration.")
                    async with get_session() as session:
                        session.add(Iteration(
                            submission_id=submission_id, iteration_num=iteration_num, code_input=code,
                            error_logs=error_logs, ai_response=ai_resp.raw, patch_applied=patch_summary,
                            status="failed", failure_reason="phpstan_failed",
                            duration_ms=int((time.time() - start_time) * 1000),
                            pipeline_logs=_safe_json_dumps(iteration_events),
                        ))
                        await session.commit()
                    previous_attempts.append({"diagnosis": ai_resp.diagnosis, "outcome": "failed",
                                              "failure_reason": "phpstan_failed", "action": "execute_plan"})
                    yield _log_event("iteration_complete", {"num": iteration_num, "success": False})
                    continue

                # Pre-flight lint the pest test (skip if partial batch)
                if getattr(ai_resp, "is_partial_batch", False):
                    pest_code = ""
                    pest_res = {"success": True, "output": "[BATCH MODE] Intermediate batch applied. Bypassing functional tests."}
                    yield _log_event("log_line", {"msg": "📦 Intermediate batch successfully applied. Bypassing Pest functional tests."})
                else:
                    # Generate Pest test from AI output
                    cleaned_pest = ai_resp.pest_test.replace("?>", "").replace("```php", "").replace("```", "").strip() if ai_resp.pest_test else ""
                    if not cleaned_pest and last_pest_code:
                        logger.info(f"[{submission_id}] AI returned empty pest_test — reusing last_pest_code from previous iteration.")
                        pest_code = last_pest_code
                    else:
                        pest_code = sandbox.prepare_pest_test(cleaned_pest, class_info.fqcn)

                    # Pre-flight lint the pest test
                    preflight_path = "tests/Feature/PestPreflightTest.php"
                    await sandbox.write_file(container, preflight_path, pest_code)
                    lint_ok, lint_msg = await sandbox.lint_php(container, preflight_path)
                    if not lint_ok:
                        error_logs += f"\n\nPEST SYNTAX ERROR:\n{lint_msg}"
                        try:
                            pm_res = await ai_service.get_post_mortem(
                                code, [{"action": p.action, "path": p.target} for p in ai_resp.patches],
                                f"Pest test syntax error:\n{lint_msg}",
                                await sandbox.capture_laravel_log(container), boost_ctx, failure_reason="syntax_error"
                            )
                            pm_cat, pm_strat = pm_res.category, pm_res.strategy
                            current_post_mortem = f"Analysis: {pm_res.analysis}\nCategory: {pm_res.category}\nStrategy: {pm_res.strategy}"
                        except Exception:
                            pm_cat, pm_strat = "test", "Generate syntactically valid Pest test code"
                        async with get_session() as session:
                            session.add(Iteration(
                                submission_id=submission_id, iteration_num=iteration_num, code_input=code,
                                error_logs=error_logs, ai_response=ai_resp.raw, patch_applied=patch_summary,
                                pest_test_code=pest_code, status="failed", failure_reason="test_syntax_error",
                                failure_details=f"Pest syntax: {lint_msg}", pm_category=pm_cat, pm_strategy=pm_strat,
                                duration_ms=int((time.time() - start_time) * 1000),
                                pipeline_logs=_safe_json_dumps(iteration_events),
                            ))
                            await session.commit()
                        previous_attempts.append({"diagnosis": ai_resp.diagnosis, "outcome": "failed",
                                                  "failure_reason": "test_syntax_error", "action": "execute_plan"})
                        yield _log_event("iteration_complete", {"num": iteration_num, "success": False})
                        continue

                    yield _log_event("log_line", {"msg": "Running Pest functional tests..."})
                    t_pest = time.monotonic()
                    if not pest_code:
                        # Guard: never run pest with an empty test file — mark as failure
                        pest_res = {"success": False, "output": "[SYSTEM] AI generated no Pest test code — treating as failure."}
                        logger.warning(f"[{submission_id}] AI returned empty pest_test — marking iteration as failed.")
                    else:
                        pest_res = await sandbox.run_pest_test(container, pest_code)
                    logger.info(f"[{submission_id}] Pest took {int((time.monotonic() - t_pest)*1000)}ms")

            # ── PATH B: Compilation already clean → run AI-generated test ────
            else:
                if last_pest_code:
                    # We have an AI-generated test from a previous iteration — run it
                    yield _log_event("log_line", {"msg": "Compilation OK. Running previous AI-generated Pest test..."})
                    pest_code = last_pest_code
                    t_pest = time.monotonic()
                    pest_res = await sandbox.run_pest_test(container, pest_code)
                    logger.info(f"[{submission_id}] Pest (reused) took {int((time.monotonic() - t_pest)*1000)}ms")
                else:
                    # First clean compile — AI must generate a test to verify the logic
                    yield _log_event("log_line", {"msg": "Compilation OK. Calling AI to generate verification test..."})
                    boost_ctx_raw = await boost_service.get_boost_context(container_id, error_logs, submission_id)
                    try:
                        boost_parsed = json.loads(boost_ctx_raw)
                        boost_component_type = boost_parsed.get("component_type", "unknown")
                        boost_ctx = boost_parsed.get("schema_info", "") + "\n" + "\n".join(boost_parsed.get("docs_excerpts", []))
                    except (json.JSONDecodeError, AttributeError):
                        boost_ctx = boost_ctx_raw
                    boost_ctx = placement_hint + boost_ctx
                    async with get_session() as session:
                        past_repairs = await context.get_similar_repairs(session, error_logs)
                    escalation_ctx = escalation_service.build_escalation_context(previous_attempts)
                    try:
                        async for evt_type, evt_data in pipeline.run_pipeline(
                            code, structured_error_for_llm, boost_ctx, previous_attempts,
                            past_repairs, prompt, escalation_ctx, current_post_mortem,
                            iteration_num=iteration_num, max_iters=max_iters
                        ):
                            if evt_type == "final_result":
                                ai_resp, models = evt_data
                            elif evt_type == "approved_plan":
                                plan_to_use = evt_data
                            else:
                                yield _log_event(evt_type, evt_data)
                    except Exception as pipeline_exc:
                        logger.error(f"[{submission_id}] Test-gen pipeline failed: {pipeline_exc}")
                    if ai_resp and ai_resp.pest_test:
                        cleaned = ai_resp.pest_test.replace("?>", "").replace("```php", "").replace("```", "").strip()
                        pest_code = sandbox.prepare_pest_test(cleaned, class_info.fqcn)
                    else:
                        pest_code = ""
                    t_pest = time.monotonic()
                    if not pest_code:
                        pest_res = {"success": False, "output": "[SYSTEM] No Pest test code generated for clean compile — marking as failed to force retry."}
                        logger.warning(f"[{submission_id}] Clean compile but no test generated — forcing retry.")
                    else:
                        pest_res = await sandbox.run_pest_test(container, pest_code)
                    logger.info(f"[{submission_id}] Pest (generated) took {int((time.monotonic() - t_pest)*1000)}ms")

            # ── Save test for next iteration ─────────────────────────────────
            if pest_code:
                last_pest_code = pest_code

            # ── Shared gate evaluation (both paths land here) ─────────────────
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

            if not pest_res["success"] and ai_resp:
                failure_reason = "pest_failed"
                failure_details = pest_res.get("output", "")[:500]
                try:
                    pm_res = await ai_service.get_post_mortem(
                        code, [{"action": p.action, "path": p.target} for p in ai_resp.patches],
                        pest_res["output"], await sandbox.capture_laravel_log(container),
                        boost_ctx, failure_reason="pest_failed"
                    )
                    current_post_mortem = f"Analysis: {pm_res.analysis}\nCategory: {pm_res.category}\nStrategy: {pm_res.strategy}"
                    pm_category, pm_strategy = pm_res.category, pm_res.strategy
                    yield _log_event("log_line", {"msg": f"Critic Analysis: {pm_res.category}"})
                except Exception as pm_exc:
                    logger.warning(f"[{submission_id}] PostMortem skipped: {pm_exc}")

            # Mutation gate
            mutation_score = None
            if pest_res["success"] and kwargs.get("use_mutation_gate", True) and not getattr(ai_resp, "is_partial_batch", False):
                yield _log_event("log_line", {"msg": "Pest passed. Running Mutation Gate..."})
                t_mut = time.monotonic()
                mutation_res = await sandbox.run_mutation_test(container)
                logger.info(f"[{submission_id}] Mutation took {int((time.monotonic() - t_mut)*1000)}ms")
                mutation_score = mutation_res.score
                if not mutation_res.passed:
                    failure_reason = "mutation_failed"
                    failure_details = f"Score: {mutation_score}%"
                    error_logs += f"\n\nMUTATION GATE FAILURE (Score: {mutation_score}%):\n{mutation_res.output}"
                    try:
                        # Pass the patched file content, not the original broken code,
                        # so the critic evaluates the correct (fixed) state when diagnosing test gaps.
                        _patched_code = code
                        if ai_resp and ai_resp.patches:
                            _first_ok_patch = next(
                                (p for p in ai_resp.patches if apply_res.get(p.target or p.filename, False)),
                                None
                            )
                            if _first_ok_patch:
                                try:
                                    _patched_code = await sandbox.read_file(
                                        container, _first_ok_patch.target or _first_ok_patch.filename
                                    )
                                except Exception:
                                    pass  # fall back to original code
                        pm_res = await ai_service.get_post_mortem(
                            _patched_code,
                            [{"action": p.action, "path": p.target} for p in ai_resp.patches] if ai_resp else [],
                            f"Mutation Gate Failed with score {mutation_score}%.\n{mutation_res.output}",
                            await sandbox.capture_laravel_log(container), boost_ctx,
                            failure_reason="mutation_failed"
                        )
                        current_post_mortem = f"Analysis: {pm_res.analysis}\nCategory: {pm_res.category}\nStrategy: {pm_res.strategy}"
                        pm_category, pm_strategy = pm_res.category, pm_res.strategy
                        yield _log_event("log_line", {"msg": f"Critic Analysis (Mutation): {pm_res.category}"})
                    except Exception as pm_exc:
                        logger.warning(f"[{submission_id}] Mutation PostMortem skipped: {pm_exc}")
                yield _log_event("mutation_result", {
                    "score": mutation_score, "passed": mutation_res.passed,
                    "duration_ms": int((time.time() - start_time) * 1000),
                })

            # Evaluate final outcome
            success = pest_res["success"] and (
                mutation_score is None or mutation_score >= settings.mutation_score_threshold
            ) and not getattr(ai_resp, "is_partial_batch", False)
            it_status = "success" if success else "failed"

            logger.info(
                f"[{submission_id}] ITERATION {iteration_num} SUMMARY: "
                f"Status: {it_status} | Pest: {'PASS' if pest_res['success'] else 'FAIL'} | "
                f"Mutation: {mutation_score if mutation_score is not None else 'N/A'}% | "
                f"Models: {json.dumps(models)}"
            )

            async with get_session() as session:
                session.add(Iteration(
                    submission_id=submission_id,
                    iteration_num=iteration_num,
                    code_input=code,
                    error_logs=error_logs,
                    ai_response=ai_resp.raw if ai_resp else "N/A",
                    ai_prompt=getattr(ai_resp, "prompt", "") if ai_resp else "",
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
                    pipeline_logs=_safe_json_dumps(iteration_events),
                ))
                await session.commit()

            previous_attempts.append({
                "diagnosis": ai_resp.diagnosis if ai_resp else "N/A",
                "outcome": it_status,
                "files": list(created_files),
                "failure_reason": failure_reason,
                "failure_details": failure_details,
                "pm_category": pm_category,
                "pm_strategy": pm_strategy,
                "fix_description": ai_resp.fix_description if ai_resp else "",
                "action": "execute_plan",
                "is_partial_batch": getattr(ai_resp, "is_partial_batch", False),
                "approved_plan": plan_to_use,
            })

            yield _log_event("iteration_complete", {"num": iteration_num, "success": success})

            if success:
                async with get_session() as session:
                    submission_obj = (
                        await session.execute(select(Submission).where(Submission.id == submission_id))
                    ).scalar_one()
                    submission_obj.status = "success"
                    if primary_target_file:
                        submission_obj.final_code = await sandbox.read_file(container, primary_target_file)
                    elif ai_resp and ai_resp.patches:
                        submission_obj.final_code = await sandbox.read_file(container, ai_resp.patches[0].target)
                    else:
                        submission_obj.final_code = code
                    if ai_resp:
                        await context.store_repair_success(session, error_logs, ai_resp, iteration_num)
                    submission_obj.total_iterations = iteration_num
                    await session.commit()
                yield _log_event("log_line", {"msg": "✅ JOB DONE: Success! All tests passed and mutation gate satisfied."})
                yield _log_event("complete", {"status": "success", "iterations": iteration_num, "mutation_score": mutation_score})
                return

            async with get_session() as session:
                submission_obj = (
                    await session.execute(select(Submission).where(Submission.id == submission_id))
                ).scalar_one()
                submission_obj.total_iterations = iteration_num
                await session.commit()

        # Loop exhausted
        try:
            async with get_session() as session:
                submission_obj = (
                    await session.execute(select(Submission).where(Submission.id == submission_id))
                ).scalar_one()
                submission_obj.status = "failed"
                await session.commit()
        except Exception:
            pass
        yield {"event": "log_line", "data": {"msg": "❌ JOB DONE: Failed. Max iterations reached without a stable fix."}}
        yield {"event": "complete", "data": {"status": "failed", "iterations": max_iters, "mutation_score": None}}

    except Exception as e:
        is_cancelled = False
        try:
            async with get_session() as session:
                submission_obj = (
                    await session.execute(select(Submission).where(Submission.id == submission_id))
                ).scalar_one()
                await session.refresh(submission_obj)
                is_cancelled = submission_obj.is_cancelled
        except Exception:
            pass

        if is_cancelled:
            logger.info(f"[{submission_id}] Orchestrator caught termination of cancelled job.")
            yield {"event": "complete", "data": {"status": "cancelled", "iterations": locals().get('iteration_num', 0)}}
        else:
            logger.exception(f"[{submission_id}] Fatal error: {e}")
            try:
                async with get_session() as session:
                    submission_obj = (
                        await session.execute(select(Submission).where(Submission.id == submission_id))
                    ).scalar_one()
                    submission_obj.status = "failed"
                    submission_obj.error_summary = str(e)
                    await session.commit()
            except Exception:
                pass
            yield {"event": "error", "data": {"msg": str(e)}}
            yield {"event": "complete", "data": {"status": "failed", "iterations": locals().get('iteration_num', 0)}}
    finally:
        if 'container_id' in locals():
            await sandbox.destroy_sandbox(container_id)
        from api.routers.repair import _event_queues, _repair_done
        _repair_done[submission_id] = True
