
import pytest
from unittest.mock import AsyncMock, patch
from api.services.repair.pipeline import run_pipeline

@pytest.mark.asyncio
async def test_run_pipeline_orchestration():
    """Verify that the pipeline correctly sequences AI roles."""
    with (
        patch("api.services.ai_service.get_plan", AsyncMock(return_value=AsyncMock(raw="{}", data={}, model_used="m1"))) as m_plan,
        patch("api.services.ai_service.verify_plan", AsyncMock(return_value=AsyncMock(approved_plan={}, model_used="m2"))) as m_verify,
        patch("api.services.ai_service.execute_plan", AsyncMock(return_value=AsyncMock(response=AsyncMock(), model_used="m3"))) as m_exec,
        patch("api.services.ai_service.review_output", AsyncMock(return_value=AsyncMock(validated_output=None, model_used="m4"))) as m_review,
    ):
        resp, models = await run_pipeline("code", "error", "boost", [], "", "prompt", "")
        
        assert m_plan.called
        assert m_verify.called
        assert m_exec.called
        assert m_review.called
        assert models["planner"] == "m1"
        assert models["executor"] == "m3"
