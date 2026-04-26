from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.services.docker_service import ExecResult
from api.services.sandbox_service import (
    ensure_covers_directive,
    parse_mutation_score_details,
    run_mutation_test,
)


def test_parse_mutation_score_details_no_match_returns_none_pattern():
    score, pattern = parse_mutation_score_details("output without mutation percentage")
    assert score == 0.0
    assert pattern is None


def test_ensure_covers_directive_fallback_uses_single_php_namespace_slashes():
    test_code = "<?php\ntest('x', fn () => expect(true)->toBeTrue());\n"
    current_code = "<?php\nnamespace App\\Http\\Controllers;\nclass DemoController {}\n"

    result = ensure_covers_directive(test_code, current_code, None)

    assert "covers(\\App\\Http\\Controllers\\DemoController::class);" in result
    assert "covers(\\\\App\\\\Http\\\\Controllers\\\\DemoController::class);" not in result


@pytest.mark.asyncio
async def test_run_mutation_test_prefixes_output_when_score_unparsed():
    container = MagicMock()
    exec_result = ExecResult(
        stdout="mutation run complete but score format changed",
        stderr="",
        exit_code=0,
        duration_ms=123,
    )

    with patch(
        "api.services.sandbox_service.docker_service.execute",
        AsyncMock(return_value=exec_result),
    ) as mock_execute:
        result = await run_mutation_test(container)

    assert result.score == 0.0
    assert "MUTATION_PARSE_WARNING" in result.output
    called_timeout = mock_execute.await_args.kwargs.get("timeout")
    from api.services.sandbox_service import settings

    assert called_timeout == settings.mutation_timeout_seconds
