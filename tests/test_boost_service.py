"""
tests/test_boost_service.py — Unit tests for api/services/boost_service.py
Mocks docker_service.execute so no real container needed.
"""
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

    def test_to_prompt_text_includes_schema(self):
        ctx = BoostContext(schema_info="products: id, name", docs_excerpts=[], component_type="model")
        text = ctx.to_prompt_text()
        assert "products: id, name" in text
        assert "## Schema" in text

    def test_to_prompt_text_empty_returns_fallback(self):
        ctx = BoostContext(schema_info="", docs_excerpts=[], component_type="unknown")
        text = ctx.to_prompt_text()
        assert text == ""


class TestCacheKey:
    def test_same_error_same_key(self):
        err = "Class App\\Models\\Product not found"
        assert _cache_key("sub-1", err) == _cache_key("sub-1", err)

    def test_different_component_different_key(self):
        # Different errors with different component types generate different keys
        assert _cache_key("sub-1", "Eloquent model missing") != _cache_key("sub-1", "Route [api.users] not defined")

    def test_different_submission_different_key(self):
        err = "same error"
        assert _cache_key("sub-1", err) != _cache_key("sub-2", err)

    def test_key_is_consistent_across_calls(self):
        err = "Fatal error: Call to undefined function"
        k1 = _cache_key("sub-1", err)
        k2 = _cache_key("sub-1", err)
        assert k1 == k2




class TestDetectComponentType:
    @pytest.mark.parametrize("error,expected", [
        ("Controller not found", "controller"),
        ("Eloquent model missing", "model"),
        ("migration failed: Schema error", "migration"),
        ("Middleware stack broken", "middleware"),
        ("Route [api.users] not defined", "route"),
        ("Request validation failed", "request"),
        ("Something totally unrelated", "unknown"),
    ])
    def test_detection(self, error, expected):
        assert _detect_component_type(error) == expected


@pytest.mark.asyncio
class TestQueryContext:
    async def test_cache_hit_skips_docker_call(self):
        # Pre-populate cache
        key = _cache_key("sub-cached", "cached error")
        boost_service._cache[key] = json.dumps({"schema_info": "cached", "docs_excerpts": [], "component_type": "unknown"})

        container = MagicMock()
        result = await boost_service.query_context(container, "cached error", submission_id="sub-cached")
        data = json.loads(result)
        assert data["schema_info"] == "cached"
        # container should not have been used
        container.exec_run.assert_not_called()

    async def test_empty_context_returned_on_docker_failure(self):
        # Clear cache so it runs
        boost_service._cache.clear()

        fake_exec = AsyncMock()
        fake_exec.return_value = MagicMock(exit_code=1, stdout="", stderr="error")

        with patch("api.services.boost_service.docker_service.execute", fake_exec):
            container = MagicMock()
            result = await boost_service.query_context(container, "some new error xyz123")
            data = json.loads(result)
            assert "No schema info" in data["schema_info"]
