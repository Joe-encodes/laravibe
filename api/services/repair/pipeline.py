
import logging
import api.services.ai_service as ai_service

logger = logging.getLogger(__name__)

async def run_pipeline(code, error, boost, prev, past, prompt, escalation_ctx, post_mortem=None, iteration_num=1):
    """
    Planner -> Verifier -> Executor -> Reviewer pipeline.
    Yields (event_type, event_data) tuples for real-time FE observability.
    The final yield is the (final_response, model_map) tuple.
    """
    plan_to_use = None
    planner_model = "skipped"
    verifier_model = "skipped"

    # --- FAST-REFINE SHORTCUT ---
    # Only use Fast-Refine if the PREVIOUS iteration wasn't also a Fast-Refine that failed.
    # We check if the strategy is repeating to avoid infinite loops.
    is_repeated_strategy = False
    if post_mortem and prev:
        last_strategy = prev[-1].get("pm_strategy", "") if prev else ""
        if post_mortem.strategy == last_strategy:
            is_repeated_strategy = True

    is_simple_refinement = (
        iteration_num > 1 and 
        post_mortem and 
        post_mortem.category in ["syntax", "dependency", "missing_import"] and
        not is_repeated_strategy
    )
    
    if is_simple_refinement:
        yield "log_line", {"msg": f"⚡ Fast-Refine Mode engaged for {post_mortem.category}. Skipping Planner/Verifier."}
        plan_to_use = {
            "error_classification": post_mortem.category,
            "root_cause": post_mortem.analysis,
            "repair_steps": [post_mortem.strategy],
            "files_to_modify": post_mortem.files_implicated or []
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
    
    # 3. Executor
    yield "ai_thinking", {"role": "Executor", "status": "Generating PHP patches..."}
    exec_result = await ai_service.execute_plan(
        code, error, boost, plan_to_use, escalation_ctx, 
        post_mortem_strategy=(post_mortem.strategy if post_mortem else ""),
        user_prompt=prompt
    )
    yield "api_call", {"role": "Executor", "model": exec_result.model_used, "output": exec_result.response.raw[:500]}
    
    if exec_result.response.thought_process == "PARSING_FAILED":
        yield "final_result", (ai_service.AIRepairResponse(
            thought_process="Executor output parsing failed",
            diagnosis="Unknown (parsing failed)",
            fix_description="Executor failed to produce valid XML",
            patches=[],
            pest_test="",
            prompt=prompt,
            raw=exec_result.response.raw
        ), {"planner": planner_model, "verifier": verifier_model, "executor": exec_result.model_used})
        return

    # 4. Reviewer
    yield "ai_thinking", {"role": "Reviewer", "status": "Validating patch syntax..."}
    review_result = await ai_service.review_output(exec_result.response.raw, plan_to_use)
    yield "api_call", {"role": "Reviewer", "model": review_result.model_used, "feedback": review_result.evidence_for_next_cycle[:200] if review_result.evidence_for_next_cycle else "None"}
    
    final_resp = review_result.validated_output or exec_result.response
    final_resp.reviewer_evidence = review_result.evidence_for_next_cycle

    yield "final_result", (final_resp, {
        "planner": planner_model,
        "verifier": verifier_model,
        "executor": exec_result.model_used,
        "reviewer": review_result.model_used
    })
