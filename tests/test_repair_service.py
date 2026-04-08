"""
tests/test_repair_service.py — Unit tests for api/services/repair_service.py
All Docker, AI, and Boost calls are mocked — no real containers or API keys needed.
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from api.services.repair_service import run_repair_loop, _parse_mutation_score


# ─────────────────────────────────────────────────────────────────────────────
# Helper: collect all SSE events from the async generator into a list
# ─────────────────────────────────────────────────────────────────────────────
async def _collect(gen) -> list[dict]:
    events = []
    async for evt in gen:
        events.append(evt)
    return events


def _make_exec(stdout="", stderr="", exit_code=0, duration_ms=50):
    from api.services.docker_service import ExecResult
    return ExecResult(stdout=stdout, stderr=stderr, exit_code=exit_code, duration_ms=duration_ms)


def _make_ai_resp(action="replace", target="<?php", diagnosis="missing import"):
    from api.services.ai_service import AIRepairResponse, PatchSpec
    return AIRepairResponse(
        diagnosis=diagnosis,
        fix_description="Added missing use statement",
        patch=PatchSpec(action=action, target=target, replacement="<?php\nuse App\\Models\\Product;", filename=None),
        pest_test="it('works', fn() => expect(true)->toBeTrue());",
        raw=json.dumps({"diagnosis": diagnosis, "fix_description": "fix", "patch": {}, "pest_test": ""}),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def mock_submission():
    sub = MagicMock()
    sub.id = "test-sub-id"
    sub.status = "pending"
    sub.total_iterations = 0
    sub.final_code = None
    sub.error_summary = None
    return sub


@pytest.fixture
def mock_db(mock_submission):
    db = AsyncMock()
    db.get = AsyncMock(return_value=mock_submission)
    db.add = MagicMock()
    db.commit = AsyncMock()
    return db


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
class TestParseMutationScore:
    async def test_parses_mutation_score_percentage(self):
        output = "Results: 85.5% mutation score achieved"
        assert _parse_mutation_score(output) == 85.5

    async def test_parses_score_label(self):
        assert _parse_mutation_score("Score: 92%") == 92.0

    async def test_returns_zero_on_no_match(self):
        assert _parse_mutation_score("no score info here") == 0.0

    async def test_parses_mutations_label(self):
        assert _parse_mutation_score("Mutations: 78.3%") == 78.3


@pytest.mark.asyncio
class TestRepairLoopSuccess:
    async def test_success_on_first_iteration(self, mock_db, mock_submission):
        """Loop should emit 'complete' with status=success when code runs clean."""

        # The repair loop calls execute in this order per iteration (when lint passes):
        #   1. php -l lint check
        #   2. grep namespace  (stdout: namespace string)
        #   3. grep classname  (stdout: class name)
        #   4. artisan tinker setup+class check  (stdout: CLASS_OK)
        #   5. pest --filter=RepairTest
        #   6. pest --mutate
        lint_ok  = _make_exec(stdout="No syntax errors detected", exit_code=0)
        ns_ok    = _make_exec(stdout="App/Http/Controllers", exit_code=0)
        cls_ok   = _make_exec(stdout="TestClass", exit_code=0)
        tinker_ok = _make_exec(stdout="CLASS_OK", exit_code=0)
        pest_ok  = _make_exec(stdout="Tests: 1 passed", exit_code=0)
        mut_ok   = _make_exec(stdout="Score: 85% mutation score", exit_code=0)

        with (
            patch("api.services.repair_service.docker_service.create_container", AsyncMock(return_value=MagicMock())),
            patch("api.services.repair_service.docker_service.copy_code", AsyncMock()),
            patch("api.services.repair_service.docker_service.execute",
                  AsyncMock(side_effect=[lint_ok, ns_ok, cls_ok, tinker_ok, pest_ok, mut_ok])),
            patch("api.services.repair_service.docker_service.destroy", AsyncMock()),
            patch("api.services.repair_service.boost_service.query_context",
                  AsyncMock(return_value=json.dumps({"schema_info": "", "docs_excerpts": [], "component_type": "unknown"}))),
        ):
            events = await _collect(run_repair_loop("test-sub-id", "<?php echo 'hi';", mock_db))

        complete = next(e for e in events if e["event"] == "complete")
        assert complete["data"]["status"] == "success"
        assert complete["data"]["mutation_score"] >= 80


@pytest.mark.asyncio
class TestRepairLoopFailed:
    async def test_exhausts_max_iterations(self, mock_db, mock_submission):
        """Loop should emit 'complete' with status=failed after max iterations."""

        err_exec = _make_exec(stderr="Fatal error: Class not found", exit_code=255)
        ai_resp = _make_ai_resp()
        boost_ctx = json.dumps({"schema_info": "", "docs_excerpts": [], "component_type": "model"})

        with (
            patch("api.services.repair_service.docker_service.create_container", AsyncMock(return_value=MagicMock())),
            patch("api.services.repair_service.docker_service.copy_code", AsyncMock()),
            patch("api.services.repair_service.docker_service.execute", AsyncMock(return_value=err_exec)),
            patch("api.services.repair_service.docker_service.destroy", AsyncMock()),
            patch("api.services.repair_service.boost_service.query_context", AsyncMock(return_value=boost_ctx)),
            patch("api.services.repair_service.ai_service.get_repair", AsyncMock(return_value=ai_resp)),
        ):
            events = await _collect(
                run_repair_loop("test-sub-id", "<?php class Broken {}", mock_db, max_iterations=2)
            )

        complete = next(e for e in events if e["event"] == "complete")
        assert complete["data"]["status"] == "failed"
        assert complete["data"]["iterations"] == 2


@pytest.mark.asyncio
class TestRepairLoopMutationWeak:
    async def test_continues_when_mutation_score_low(self, mock_db, mock_submission):
        """When Pest passes but mutation score < 80%, loop should continue."""

        # Iteration 1: lint passes → namespace/class detect → tinker ok → pest pass → mutation weak
        lint_ok   = _make_exec(stdout="No syntax errors detected", exit_code=0)
        ns_ok     = _make_exec(stdout="App/Http/Controllers", exit_code=0)
        cls_ok    = _make_exec(stdout="TestClass", exit_code=0)
        tinker_ok = _make_exec(stdout="CLASS_OK", exit_code=0)
        pest_ok   = _make_exec(stdout="Tests: 1 passed", exit_code=0)
        mut_weak  = _make_exec(stdout="Score: 50% mutation score", exit_code=0)  # fails gate
        # Iteration 2: lint fails immediately → triggers AI → loop exhausts
        err_exec  = _make_exec(stderr="Fatal error", exit_code=1)
        ai_resp = _make_ai_resp()
        boost_ctx = json.dumps({"schema_info": "", "docs_excerpts": [], "component_type": "unknown"})

        # Sequence: iter1 full flow (6 calls) + iter2 lint fail (1 call) + padding
        call_sequence = [lint_ok, ns_ok, cls_ok, tinker_ok, pest_ok, mut_weak, err_exec]
        with (
            patch("api.services.repair_service.docker_service.create_container", AsyncMock(return_value=MagicMock())),
            patch("api.services.repair_service.docker_service.copy_code", AsyncMock()),
            patch("api.services.repair_service.docker_service.execute",
                  AsyncMock(side_effect=call_sequence + [err_exec] * 20)),
            patch("api.services.repair_service.docker_service.destroy", AsyncMock()),
            patch("api.services.repair_service.boost_service.query_context", AsyncMock(return_value=boost_ctx)),
            patch("api.services.repair_service.ai_service.get_repair", AsyncMock(return_value=ai_resp)),
        ):
            events = await _collect(
                run_repair_loop("test-sub-id", "<?php", mock_db, max_iterations=2)
            )

        mutation_events = [e for e in events if e["event"] == "mutation_result"]
        assert len(mutation_events) >= 1
        assert mutation_events[0]["data"]["passed"] is False
