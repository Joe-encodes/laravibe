
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from api.services.repair.pipeline import run_pipeline

async def _get_result(gen):
    resp = None
    models = {}
    async for evt, data in gen:
        if evt == "final_result":
            resp, models = data
    return resp, models

@pytest.mark.asyncio
async def test_run_pipeline_success():
    """Happy path: All stages pass."""
    ai_resp = MagicMock()
    with (
        patch("api.services.ai_service.get_plan", AsyncMock(return_value=MagicMock(data={"repair_steps": []}, model_used="m1"))),
        patch("api.services.ai_service.verify_plan", AsyncMock(return_value=MagicMock(verdict="APPROVE", approved_plan=None, model_used="m2"))),
        patch("api.services.ai_service.execute_plan", AsyncMock(return_value=MagicMock(response=ai_resp, model_used="m3"))),
        patch("api.services.ai_service.review_output", AsyncMock(return_value=MagicMock(validated_output=None, evidence_for_next_cycle=None, model_used="m4"))),
    ):
        resp, models = await _get_result(run_pipeline("code", "error", "boost", [], "", "prompt", ""))
        assert resp == ai_resp
        assert models["planner"] == "m1"

@pytest.mark.asyncio
async def test_run_pipeline_planner_fails():
    """If planner returns invalid JSON, it should yield a fallback result instead of raising."""
    with patch("api.services.ai_service.get_plan", AsyncMock(return_value=MagicMock(data={}, raw="{}", model_used="m1"))):
        resp, models = await _get_result(run_pipeline("code", "error", "boost", [], "", "prompt", ""))
        assert resp.thought_process == "Planner parsing failed"
        assert models["planner"] == "m1"

@pytest.mark.asyncio
async def test_run_pipeline_verifier_rejects_with_fallback():
    """If verifier rejects but provides a fix, we use the fallback."""
    ai_resp = MagicMock()
    fallback_plan = {"repair_steps": ["fallback"]}
    with (
        patch("api.services.ai_service.get_plan", AsyncMock(return_value=MagicMock(data={"repair_steps": ["bad"]}, model_used="m1"))),
        patch("api.services.ai_service.verify_plan", AsyncMock(return_value=MagicMock(verdict="REJECT", reason="bad", approved_plan=fallback_plan, model_used="m2"))),
        patch("api.services.ai_service.execute_plan", AsyncMock(return_value=MagicMock(response=ai_resp, model_used="m3"))) as m_exec,
        patch("api.services.ai_service.review_output", AsyncMock(return_value=MagicMock(validated_output=None, evidence_for_next_cycle=None, model_used="m4"))),
    ):
        await _get_result(run_pipeline("code", "error", "boost", [], "", "prompt", ""))
        # Ensure the executor received the fallback plan
        m_exec.assert_called_with("code", "error", "boost", fallback_plan, "", post_mortem_strategy="", user_prompt="prompt")

@pytest.mark.asyncio
async def test_run_pipeline_verifier_rejects_no_fallback():
    """If verifier rejects and provides NO fix, it should proceed with the original plan."""
    ai_resp = MagicMock()
    original_plan = {"repair_steps": ["bad"]}
    with (
        patch("api.services.ai_service.get_plan", AsyncMock(return_value=MagicMock(data=original_plan, model_used="m1"))),
        patch("api.services.ai_service.verify_plan", AsyncMock(return_value=MagicMock(verdict="REJECT", reason="very bad", approved_plan=None, model_used="m2"))),
        patch("api.services.ai_service.execute_plan", AsyncMock(return_value=MagicMock(response=ai_resp, model_used="m3"))) as m_exec,
        patch("api.services.ai_service.review_output", AsyncMock(return_value=MagicMock(validated_output=None, evidence_for_next_cycle=None, model_used="m4"))),
    ):
        await _get_result(run_pipeline("code", "error", "boost", [], "", "prompt", ""))
        # Ensure the executor received the ORIGINAL plan because there was no fallback
        m_exec.assert_called_with("code", "error", "boost", original_plan, "", post_mortem_strategy="", user_prompt="prompt")

@pytest.mark.asyncio
async def test_run_pipeline_executor_parsing_fails():
    """If executor fails to produce valid XML, it should return a fallback response."""
    exec_res = MagicMock()
    exec_res.response.thought_process = "PARSING_FAILED"
    with (
        patch("api.services.ai_service.get_plan", AsyncMock(return_value=MagicMock(data={"repair_steps": []}, model_used="m1"))),
        patch("api.services.ai_service.verify_plan", AsyncMock(return_value=MagicMock(verdict="APPROVE", approved_plan=None, model_used="m2"))),
        patch("api.services.ai_service.execute_plan", AsyncMock(return_value=exec_res)),
    ):
        resp, models = await _get_result(run_pipeline("code", "error", "boost", [], "", "prompt", ""))
        assert resp.thought_process == "Executor output parsing failed"
