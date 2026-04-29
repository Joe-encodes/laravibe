
import logging
import api.services.ai_service as ai_service

logger = logging.getLogger(__name__)

async def run_pipeline(code, error, boost, prev, past, prompt, escalation_ctx, post_mortem=None):
    """Planner -> Verifier -> Executor -> Reviewer pipeline."""
    # 1. Planner: Analyze and plan
    plan_result = await ai_service.get_plan(code, error, boost, prev, past, post_mortem)
    
    # 2. Verifier: Verify the plan for potential flaws
    verify_result = await ai_service.verify_plan(code, error, boost, plan_result.raw, prev)
    plan_to_use = verify_result.approved_plan or plan_result.data
    
    # 3. Executor: Generate the code/patches
    exec_result = await ai_service.execute_plan(code, error, boost, plan_to_use, escalation_ctx, prompt)
    
    # 4. Reviewer: Final check on the generated code
    review_result = await ai_service.review_output(exec_result.response.raw, plan_to_use)
    
    final_resp = review_result.validated_output or exec_result.response
    models = {
        "planner": plan_result.model_used,
        "executor": exec_result.model_used,
        "reviewer": review_result.model_used
    }
    return final_resp, models
