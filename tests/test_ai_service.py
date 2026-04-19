"""
tests/test_ai_service.py — Unit tests for api/services/ai_service.py
Mocks all HTTP calls — no real AI provider needed.
"""
import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from api.services.ai_service import (
    _build_prompt,
    _parse_response,
    AIRepairResponse,
    PatchSpec,
    AIServiceError,
)


VALID_RESPONSE = json.dumps({
    "diagnosis": "Missing use statement for App\\Models\\Product",
    "fix_description": "Add the missing import at the top of the file",
    "patches": [{
        "action": "replace",
        "target": "<?php",
        "replacement": "<?php\nuse App\\Models\\Product;",
        "filename": None,
    }],
    "pest_test": "it('returns products', fn() => expect(true)->toBeTrue());",
})


class TestParseResponse:
    def test_valid_json_parsed(self):
        result = _parse_response(VALID_RESPONSE)
        assert isinstance(result, AIRepairResponse)
        assert result.diagnosis == "Missing use statement for App\\Models\\Product"
        assert result.patches[0].action == "replace"
        assert result.pest_test != ""

    def test_strips_markdown_fences(self):
        fenced = f"```json\n{VALID_RESPONSE}\n```"
        result = _parse_response(fenced)
        assert result.diagnosis != ""

    def test_plain_fences_stripped(self):
        fenced = f"```\n{VALID_RESPONSE}\n```"
        result = _parse_response(fenced)
        assert result.patches[0].action == "replace"

    def test_invalid_json_raises_value_error(self):
        with pytest.raises((ValueError, json.JSONDecodeError)):
            _parse_response("not valid json at all")

    def test_empty_optional_fields(self):
        minimal = json.dumps({
            "diagnosis": "x",
            "fix_description": "y",
            "patches": [{"action": "append", "replacement": "// fixed"}],
            "pest_test": "",
        })
        result = _parse_response(minimal)
        assert result.patches[0].target is None
        assert result.patches[0].filename is None


class TestBuildPrompt:
    def test_includes_code(self):
        prompt = _build_prompt("<?php echo 'hi';", "Fatal error", "{}", 0, [])
        assert "<?php echo 'hi';" in prompt

    def test_includes_error(self):
        prompt = _build_prompt("", "Class not found", "{}", 0, [])
        assert "Class not found" in prompt

    def test_no_previous_attempts_says_first(self):
        prompt = _build_prompt("", "err", "{}", 0, [])
        assert "first attempt" in prompt

    def test_previous_attempts_included(self):
        attempts = [{"diagnosis": "diag1", "fix_description": "fix1"}]
        prompt = _build_prompt("", "err", "{}", 1, attempts)
        assert "diag1" in prompt
        assert "fix1" in prompt


@pytest.mark.asyncio
class TestGetRepair:
    async def test_calls_llm_and_parses(self):
        with patch("api.services.ai_service._call_llm", AsyncMock(return_value=VALID_RESPONSE)):
            from api.services.ai_service import get_repair
            # Clear tenacity retry state
            result = await get_repair.__wrapped__(
                code="<?php",
                error="Fatal error",
                boost_context="{}",
                iteration=0,
                previous_attempts=[],
            )
            assert result.diagnosis != ""

    async def test_retries_on_bad_json(self):
        bad_json = "this is not json"
        good_json = VALID_RESPONSE
        call_count = 0

        async def flaky_llm(prompt):
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                return bad_json
            return good_json

        with patch("api.services.ai_service._call_llm", flaky_llm):
            from api.services.ai_service import get_repair
            result = await get_repair.__wrapped__(
                code="<?php",
                error="err",
                boost_context="{}",
                iteration=0,
                previous_attempts=[],
            )
            assert call_count >= 2
