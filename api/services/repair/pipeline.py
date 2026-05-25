
import logging
import api.services.ai_service as ai_service

logger = logging.getLogger(__name__)

async def run_pipeline(code, error, boost, prev, past, prompt, escalation_ctx, post_mortem=None, iteration_num=1, max_iters=4):
    """
    Planner -> Verifier -> Executor -> Reviewer pipeline.
    Yields (event_type, event_data) tuples for real-time FE observability.
    The final yield is the (final_response, model_map) tuple.
    """
    plan_to_use = None
    planner_model = "skipped"
    verifier_model = "skipped"

    # post_mortem is passed as a plain text string (current_post_mortem from orchestrator).
    # It is NOT a PostMortemResult object. Parse it safely.
    pm_strategy = ""
    pm_category = ""
    if post_mortem and isinstance(post_mortem, str):
        # Extract category/strategy lines if present (e.g. "Analysis: ...\nStrategy: ...")
        for line in post_mortem.splitlines():
            if line.lower().startswith("strategy:"):
                pm_strategy = line.split(":", 1)[1].strip()
            elif line.lower().startswith("category:"):
                pm_category = line.split(":", 1)[1].strip()
        if not pm_strategy:
            pm_strategy = post_mortem  # use entire string as strategy fallback

    # Check if the previous attempt had an approved plan and was a partial batch
    last_approved_plan = None
    if prev:
        last_attempt = prev[-1]
        if last_attempt.get("is_partial_batch"):
            last_approved_plan = last_attempt.get("approved_plan")

    plan_to_use = None
    planner_model = "skipped"
    verifier_model = "skipped"

    if last_approved_plan:
        yield "log_line", {"msg": "🔄 Continuing execution of the previously approved plan in batch mode."}
        plan_to_use = last_approved_plan
    else:
        # --- FAST-REFINE SHORTCUT ---
        # Only use Fast-Refine if the PREVIOUS iteration wasn't also a Fast-Refine that failed.
        is_repeated_strategy = False
        if pm_strategy and len(prev) >= 2:
            last_strategy = prev[-2].get("pm_strategy", "")
            if pm_strategy == last_strategy:
                is_repeated_strategy = True

        # Simple refinement: skip Planner/Verifier for known quick fixes.
        # mutation_gap is included: the Critic has already mandated the exact
        # strategy (rewrite pest_test only), so a full Planner/Verifier cycle
        # adds no information and wastes 2 API calls.
        FAST_REFINE_CATEGORIES = {"syntax", "dependency", "missing_import", "mutation_gap"}
        is_simple_refinement = (
            iteration_num > 1 and 
            bool(pm_strategy) and
            pm_category in FAST_REFINE_CATEGORIES and
            not is_repeated_strategy
        )
        
        if is_simple_refinement:
            if pm_category == "mutation_gap":
                yield "log_line", {"msg": "⚡ Fast-Refine Mode: Mutation gap detected. Skipping Planner/Verifier — only rewriting pest_test."}
                plan_to_use = {
                    "error_classification": "mutation_gap",
                    "root_cause": pm_strategy,
                    "repair_steps": [
                        "DO NOT modify the controller or model files.",
                        "Rewrite the <pest_test> block only with stronger mutation-killing assertions per the Critic analysis.",
                    ],
                    "files_to_modify": [],  # No file patches — only the pest_test block
                }
            else:
                yield "log_line", {"msg": f"⚡ Fast-Refine Mode engaged for '{pm_category}'. Skipping Planner/Verifier."}
                plan_to_use = {
                    "error_classification": pm_category,
                    "root_cause": post_mortem,
                    "repair_steps": [pm_strategy],
                    "files_to_modify": []
                }
        else:
            if is_repeated_strategy:
                yield "log_line", {"msg": "⚠️ Loop Detected: Strategy is repeating. Falling back to full Planner/Verifier analysis."}
            # 1. Planner
            yield "ai_thinking", {"role": "Planner", "status": "Designing repair strategy..."}
            plan_result = await ai_service.get_plan(code, error, boost, prev, past, post_mortem)
            planner_model = plan_result.model_used
            yield "api_call", {"role": "Planner", "model": planner_model, "output": plan_result.raw[:500]}
        
        if not plan_to_use:
            if not plan_result.data or "repair_steps" not in plan_result.data:
                yield "final_result", (ai_service.AIRepairResponse(
                    thought_process="Planner parsing failed",
                    diagnosis="Unknown (parsing failed)",
                    fix_description="Failed to parse Planner JSON",
                    patches=[],
                    pest_test="",
                    prompt=prompt,
                    raw=plan_result.raw
                ), {"planner": plan_result.model_used})
                return

            # 2. Verifier
            yield "ai_thinking", {"role": "Verifier", "status": "Auditing the proposed plan..."}
            verify_result = await ai_service.verify_plan(code, error, boost, plan_result.raw, prev)
            verifier_model = verify_result.model_used
            yield "api_call", {"role": "Verifier", "model": verifier_model, "verdict": verify_result.verdict}
            
            if verify_result.verdict == "REJECT":
                if verify_result.approved_plan:
                    yield "log_line", {"msg": "Verifier corrected the plan."}
                    plan_to_use = verify_result.approved_plan
                else:
                    plan_to_use = plan_result.data
            else:
                plan_to_use = verify_result.approved_plan or plan_result.data
    
    yield "approved_plan", plan_to_use

    if plan_to_use and (
        plan_to_use.get("error_classification") == "unresolvable"
        or any("abort" in str(step).lower() for step in plan_to_use.get("repair_steps", []))
    ):
        import json as _json
        reason = plan_to_use.get("root_cause") or "Planner/Verifier aborted the run due to unresolvable issues."
        yield "log_line", {"msg": f"🛑 [ABORTED] Unresolvable issue detected: {reason}. Stopping pipeline."}
        yield "final_result", (ai_service.AIRepairResponse(
            thought_process="Run aborted by Planner/Verifier",
            diagnosis=reason,
            fix_description="Aborted",
            patches=[],
            pest_test="",
            prompt=prompt,
            raw=_json.dumps(plan_to_use, ensure_ascii=False)
        ), {"planner": planner_model, "verifier": verifier_model})
        return

    # 3. Executor
    yield "ai_thinking", {"role": "Executor", "status": "Generating PHP patches..."}
    
    # Compute batching details
    files_to_modify = plan_to_use.get("files_to_modify", []) if plan_to_use else []
    created_files_set = set()
    for attempt in (prev or []):
        if "files" in attempt:
            created_files_set.update(attempt["files"])
    created_files_list = sorted(list(created_files_set))
    
    current_batch = None
    remaining_files = None
    is_partial_batch = False
    
    is_last_iteration = (iteration_num >= max_iters)

    if files_to_modify:
        remaining_files_list = [f for f in files_to_modify if f not in created_files_set]
        if remaining_files_list:
            # Dynamic batch sizing:
            # - On the last available iteration, consolidate everything.
            # - If remaining files fit in one shot (<= 4 left), do them all at once.
            # - Otherwise batch by 4 (raised from 3 to leave room for Pest + mutation gates).
            if is_last_iteration:
                batch_size = len(remaining_files_list)
            elif len(remaining_files_list) <= 4:
                batch_size = len(remaining_files_list)
            else:
                batch_size = 4
            current_batch = remaining_files_list[:batch_size]
            deferred_files = remaining_files_list[batch_size:]
            remaining_files = deferred_files
            if deferred_files and not is_last_iteration:
                is_partial_batch = True

    exec_result = await ai_service.execute_plan(
        code, error, boost, plan_to_use, escalation_ctx, 
        post_mortem_strategy=pm_strategy,
        user_prompt=prompt,
        created_files=created_files_list,
        current_batch=current_batch,
        remaining_files=remaining_files,
    )
    yield "api_call", {"role": "Executor", "model": exec_result.model_used, "output": exec_result.response.raw[:500]}
    
    exec_result.response.is_partial_batch = is_partial_batch

    if exec_result.response.thought_process == "PARSING_FAILED":
        yield "final_result", (ai_service.AIRepairResponse(
            thought_process="Executor output parsing failed",
            diagnosis="Unknown (parsing failed)",
            fix_description="Failed to produce valid XML",
            patches=[],
            pest_test="",
            prompt=prompt,
            raw=exec_result.response.raw,
            is_partial_batch=is_partial_batch
        ), {"planner": planner_model, "verifier": verifier_model, "executor": exec_result.model_used})
        return

    # 4. Reviewer
    yield "ai_thinking", {"role": "Reviewer", "status": "Validating patch syntax..."}
    review_result = await ai_service.review_output(exec_result.response.raw, plan_to_use)
    yield "api_call", {"role": "Reviewer", "model": review_result.model_used, "feedback": review_result.evidence_for_next_cycle[:200] if review_result.evidence_for_next_cycle else "None"}
    
    final_resp = review_result.validated_output or exec_result.response
    final_resp.reviewer_evidence = review_result.evidence_for_next_cycle
    final_resp.is_partial_batch = is_partial_batch

    yield "final_result", (final_resp, {
        "planner": planner_model,
        "verifier": verifier_model,
        "executor": exec_result.model_used,
        "reviewer": review_result.model_used
    })
