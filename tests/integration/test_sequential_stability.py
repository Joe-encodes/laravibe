
import pytest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch
from api.services.repair.orchestrator import run_repair_loop
from api.services.ai_service import AIRepairResponse, PatchSpec
import api.redis_client

@pytest.fixture
def mock_db():
    db = AsyncMock()
    submission = MagicMock()
    submission.id = "test-id"
    submission.status = "pending"
    db.execute = AsyncMock(return_value=MagicMock(scalar_one=lambda: submission))
    db.add = MagicMock()
    return db

async def _collect(gen):
    events = []
    async for evt in gen:
        events.append(evt)
    return events

@pytest.mark.asyncio
async def test_sequential_repair_runs_do_not_leak_resources(mock_db):
    """
    Run the orchestrator 5 times in a sequence to ensure that resource management 
    (Redis, Docker, DB) remains stable and doesn't crash the process.
    """
    ai_resp = AIRepairResponse(
        thought_process="Fix",
        diagnosis="Bug", fix_description="Fix", patches=[PatchSpec(action="full_replace", target="app/Test.php", replacement="<?php", filename="app/Test.php")],
        pest_test="<?php it('works');", raw="<repair>...</repair>", prompt="prompt", model_used="mock-m"
    )
    
    container = MagicMock()
    container.id = "container-1"
    container.short_id = "abc123de"
    
    # We run the sequence 5 times. If we were leaking connections, this might 
    # trigger OS limits or internal state issues.
    for i in range(5):
        sub_id = f"test-sub-{i}"
        with (
            patch("api.services.sandbox.create_sandbox", AsyncMock(return_value=container.id)),
            patch("api.services.sandbox.get_container", MagicMock(return_value=container)),
            patch("api.services.sandbox.detect_class_info", AsyncMock(return_value=MagicMock(fqcn="App\\Test"))),
            patch("api.services.sandbox.execute_code", AsyncMock(return_value={"output": "error"})),
            patch("api.services.boost_service.get_boost_context", AsyncMock(return_value="boost")),
            patch("api.services.repair.pipeline.run_pipeline", AsyncMock(return_value=(ai_resp, {"planner": "m"}))),
            patch("api.services.patch_service.apply_all", AsyncMock(return_value={"app/Test.php": True})),
            patch("api.services.sandbox.run_pest_test", AsyncMock(return_value={"success": True})),
            patch("api.services.sandbox.run_mutation_test", AsyncMock(return_value=MagicMock(score=85.0, passed=True))),
            patch("api.services.sandbox.read_file", AsyncMock(return_value="<?php fixed")),
            patch("api.services.sandbox.destroy_sandbox", AsyncMock()),
            patch("api.redis_client.publish_event", AsyncMock()), # Mocking publish to avoid actual Redis dependency in unit test
        ):
            events = await _collect(run_repair_loop(sub_id, "<?php", None, mock_db))
            assert any(e.get("event") == "complete" and e.get("data", {}).get("status") == "success" for e in events)

    # If we reach here, the sequence of 5 runs finished without crashing.
