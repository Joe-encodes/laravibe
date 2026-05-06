import pytest
from unittest.mock import AsyncMock, MagicMock
from api.services.repair import context
from api.models import RepairSummary

@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.add = MagicMock()
    return db

def test_similarity():
    assert context._similarity("same string", "same string") == 1.0
    assert context._similarity("hello world", "hello planet") > 0.5
    assert context._similarity("", "something") == 0.0

def test_extract_error_signature():
    assert context._extract_error_signature("local.ERROR: Missing App\\Models\\User") == "Missing App\\Models\\User"
    assert context._extract_error_signature("Some trace\nlocal.ERROR: Something { \n") == "Something"
    assert context._extract_error_signature("Exception: Fatal syntax error") == "Fatal syntax error"
    assert context._extract_error_signature("Class App\\Foo not found in bar.php") == "Class App\\Foo not found"
    assert context._extract_error_signature("Just some random text here") == "Just some random text here"
    assert context._extract_error_signature("") == "Unknown"

@pytest.mark.asyncio
async def test_ensure_cache_loaded(mock_db):
    context._cache_loaded = False
    context._repair_cache.clear()
    
    mock_res = MagicMock()
    row1 = MagicMock(error_type="err1", diagnosis="diag1", fix_applied="fix1", iterations_needed=1)
    row2 = MagicMock(error_type="err2", diagnosis="diag2", fix_applied="fix2", iterations_needed=2)
    mock_res.scalars.return_value.all.return_value = [row1, row2]
    mock_db.execute.return_value = mock_res
    
    await context._ensure_cache_loaded(mock_db)
    
    assert context._cache_loaded is True
    assert len(context._repair_cache) == 2
    assert context._repair_cache[0]["error_type"] == "err2" # reversed
    assert context._repair_cache[1]["error_type"] == "err1"
    
    # Should not query again
    mock_db.execute.reset_mock()
    await context._ensure_cache_loaded(mock_db)
    mock_db.execute.assert_not_called()

@pytest.mark.asyncio
async def test_get_similar_repairs(mock_db):
    context._cache_loaded = True
    context._repair_cache.clear()
    
    context._repair_cache.extend([
        {"error_type": "Class App\\Models\\User not found", "diagnosis": "Missing user", "fix_applied": "use App\\Models\\User", "iterations_needed": 1},
        {"error_type": "Undefined variable $foo", "diagnosis": "foo missing", "fix_applied": "$foo = 1", "iterations_needed": 2},
    ])
    
    # Exact match
    res = await context.get_similar_repairs(mock_db, "Class App\\Models\\User not found")
    assert "Past Fix 1" in res
    assert "Missing user" in res
    assert "use App\\Models\\User" in res
    
    # No match
    res = await context.get_similar_repairs(mock_db, "Syntax error somewhere totally different")
    assert res == ""

@pytest.mark.asyncio
async def test_store_repair_success(mock_db):
    context._cache_loaded = True
    context._repair_cache.clear()
    
    resp = MagicMock(diagnosis="diag", fix_description="fixed")
    await context.store_repair_success(mock_db, "local.ERROR: test error", resp, 3)
    
    assert mock_db.add.called
    added = mock_db.add.call_args[0][0]
    assert isinstance(added, RepairSummary)
    assert added.error_type == "test error"
    
    assert len(context._repair_cache) == 1
    assert context._repair_cache[-1]["error_type"] == "test error"
