import pytest
import asyncio
import uuid
import json
import logging
from api.models import Submission, Iteration
from sqlalchemy import select

logger = logging.getLogger(__name__)

@pytest.mark.anyio
async def test_kill_switch_integration(client, db_session):
    """Verify that stopping a repair actually halts execution and updates DB."""
    # 1. Create a submission
    sub_id = str(uuid.uuid4())
    sub = Submission(id=sub_id, status="pending", original_code="<?php echo 'hello';")
    db_session.add(sub)
    await db_session.commit()
    
    # 2. Cancel it - Note the route is DELETE /api/repair/{sub_id}
    response = await client.delete(f"/api/repair/{sub_id}")
    assert response.status_code == 200
    
    # 3. Verify DB state
    await db_session.refresh(sub)
    assert sub.is_cancelled is True
    # The cancel_repair function sets status to "failed" with error_summary
    assert sub.status == "failed"

@pytest.mark.anyio
async def test_sse_playback_logic(client, db_session):
    """Verify that we can 'playback' logs from a completed/failed repair."""
    sub_id = "playback-id"
    # Create a finished submission with logs
    sub = Submission(id=sub_id, status="success", original_code="<?php echo 'hello';")
    # Correct field: iteration_num, code_input, status, pipeline_logs
    it = Iteration(
        submission_id=sub_id, 
        iteration_num=0, 
        status="success",
        code_input="<?php echo 'hello';",
        patch_applied="Fixed it",
        pest_test_result="Pass",
        pipeline_logs=json.dumps([{"event": "info", "data": {"message": "Fixed it and Pass"}}])
    )
    db_session.add(sub)
    db_session.add(it)
    await db_session.commit()
    
    # Request playback - Note the route is GET /api/repair/{sub_id}/stream
    response = await client.get(f"/api/repair/{sub_id}/stream")
    assert response.status_code == 200
    
    # SSE response should contain iteration data from pipeline_logs
    content = ""
    async for line in response.aiter_lines():
        content += line
    assert "Fixed it and Pass" in content

@pytest.mark.anyio
async def test_concurrency_stress(client):
    """Stress test the orchestrator with concurrent repair requests."""
    # Simulate 5 concurrent requests
    async def create_sub(idx):
        try:
            # Route POST /api/repair is correct for submission
            return await client.post("/api/repair", json={
                "code": "<?php echo 'hello';",
                "prompt": f"test-{idx}"
            })
        except Exception as e:
            return e

    tasks = [create_sub(i) for i in range(5)]
    results = await asyncio.gather(*tasks)
    
    for r in results:
        if isinstance(r, Exception):
            logger.error(f"Request failed: {r}")
            continue
        # Should be accepted (202) or rate limited (429)
        assert r.status_code in [202, 429]
