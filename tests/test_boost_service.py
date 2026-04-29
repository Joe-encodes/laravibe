
import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from api.services import boost_service
from api.services.boost_service import (
    BoostContext,
    _cache_key,
    _detect_component_type,
)

class TestBoostContext:
    def test_to_json_roundtrip(self):
        ctx = BoostContext(
            schema_info="users table: id, name, email",
            docs_excerpts=["Use Eloquent models.", "Define relationships."],
            component_type="model",
        )
        j = ctx.to_json()
        data = json.loads(j)
        assert data["component_type"] == "model"
        assert len(data["docs_excerpts"]) == 2

    def test_empty_context(self):
        ctx = BoostContext.empty()
        assert "No schema info" in ctx.schema_info
        assert ctx.docs_excerpts == []

class TestCacheKey:
    def test_same_error_same_key(self):
        err = "Class App\\Models\\Product not found"
        assert _cache_key("sub-1", err) == _cache_key("sub-1", err)

class TestDetectComponentType:
    @pytest.mark.parametrize("error,expected", [
        ("Controller not found", "controller"),
        ("Eloquent model missing", "model"),
        ("migration failed: Schema error", "migration"),
    ])
    def test_detection(self, error, expected):
        assert _detect_component_type(error) == expected

@pytest.mark.asyncio
class TestQueryContext:
    async def test_cache_hit_skips_docker_call(self):
        # Pre-populate cache
        key = _cache_key("sub-cached", "cached error")
        import time
        boost_service._cache[key] = (json.dumps({"schema_info": "cached", "docs_excerpts": [], "component_type": "unknown"}), time.monotonic() + 3600)

        # Patch exactly what boost_service imports
        with patch("api.services.boost_service.sandbox.get_container", return_value=MagicMock()):
            result = await boost_service.query_context("container-id", "cached error", submission_id="sub-cached")
            data = json.loads(result)
            assert data["schema_info"] == "cached"

    async def test_empty_context_returned_on_docker_failure(self):
        # Clear cache so it runs
        boost_service._cache.clear()

        fake_exec = AsyncMock()
        fake_exec.return_value = MagicMock(exit_code=1, stdout="", stderr="error")

        with (
            patch("api.services.boost_service.sandbox.get_container", return_value=MagicMock()),
            patch("api.services.boost_service.docker.execute", fake_exec)
        ):
            result = await boost_service.query_context("container-id", "some new error xyz123")
            data = json.loads(result)
            assert "No schema info" in data["schema_info"]
