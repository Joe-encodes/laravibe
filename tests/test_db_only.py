import pytest
from api.models import Submission

@pytest.mark.asyncio
async def test_db_only(db_session):
    sub = Submission(id="test-id-db", original_code="<?php echo 'test'; ?>", status="pending")
    db_session.add(sub)
    await db_session.commit()
    assert True
