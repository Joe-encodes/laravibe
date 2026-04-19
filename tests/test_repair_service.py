"""
tests/test_repair_service.py — Unit tests for the refactored repair loop.

Strategy: mock sandbox_service functions directly (not docker_service.execute),
since sandbox_service is now the boundary between repair logic and container ops.
This is cleaner and doesn't depend on knowing the exact docker call sequence.
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from dataclasses import dataclass

from api.services.repair_service import run_repair_loop
from api.services.sandbox_service import parse_mutation_score as _parse_mutation_score, MutationResult, ClassInfo


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _collect(gen) -> list[dict]:
    """Collect all SSE events from the async generator."""
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
        patches=[PatchSpec(action=action, target=target, replacement="<?php\nuse App\\Models\\Product;", filename=None)],
        pest_test="it('works', fn() => expect(true)->toBeTrue());",
        raw=json.dumps({"diagnosis": diagnosis, "fix_description": "fix", "patches": [], "pest_test": ""}),
        prompt="system prompt",
    )


def _make_class_info():
    return ClassInfo(
        namespace="App/Http/Controllers",
        clean_namespace="App\\Http\\Controllers",
        classname="TestClass",
        dest_file="/var/www/sandbox/app/Http/Controllers/TestClass.php",
        fqcn="App\\\\Http\\\\Controllers\\\\TestClass",
        route_resource="tests",
    )


# ── Fixtures ──────────────────────────────────────────────────────────────────

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


# ── Mutation Score Parser Tests ───────────────────────────────────────────────

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

    async def test_parses_killed_format(self):
        assert _parse_mutation_score("15 tested, 12 killed (80.0%), 3 survived") == 80.0


# ── Repair Loop: Success Path ─────────────────────────────────────────────────

@pytest.mark.asyncio
class TestRepairLoopSuccess:
    async def test_success_on_first_iteration(self, mock_db, mock_submission):
        """Loop should emit 'complete' with status=success when code runs clean."""

        lint_ok = _make_exec(stdout="No syntax errors detected", exit_code=0)
        tinker_ok = _make_exec(stdout="CLASS_OK", exit_code=0)
        pest_ok = _make_exec(stdout="Tests: 1 passed", exit_code=0)

        mock_mut = MutationResult(score=85.0, passed=True, output="Score: 85%", duration_ms=500)

        with (
            patch("api.services.repair_service.docker_service.create_container", AsyncMock(return_value=MagicMock())),
            patch("api.services.repair_service.docker_service.ping", AsyncMock(return_value=True)),
            patch("api.services.repair_service.docker_service.copy_code", AsyncMock()),
            patch("api.services.repair_service.docker_service.execute", AsyncMock(return_value=lint_ok)),
            patch("api.services.repair_service.docker_service.destroy", AsyncMock()),
            patch("api.services.repair_service.sandbox_service.setup_sqlite", AsyncMock()),
            patch("api.services.repair_service.sandbox_service.reinject_files", AsyncMock()),
            patch("api.services.repair_service.sandbox_service.inject_pest_test", AsyncMock()),
            patch("api.services.repair_service.sandbox_service.detect_class_info", AsyncMock(return_value=_make_class_info())),
            patch("api.services.repair_service.sandbox_service.place_code_in_laravel", AsyncMock(return_value=tinker_ok)),
            patch("api.services.repair_service.sandbox_service.scaffold_route", AsyncMock()),
            patch("api.services.repair_service.sandbox_service.run_pest_test", AsyncMock(return_value=pest_ok)),
            patch("api.services.repair_service.sandbox_service.run_mutation_test", AsyncMock(return_value=mock_mut)),
            patch("api.services.repair_service.boost_service.query_context",
                  AsyncMock(return_value=json.dumps({"schema_info": "", "docs_excerpts": [], "component_type": "unknown"}))),
        ):
            events = await _collect(run_repair_loop("test-sub-id", "<?php echo 'hi';", mock_db))

        complete = next(e for e in events if e["event"] == "complete")
        assert complete["data"]["status"] == "success"
        assert complete["data"]["mutation_score"] is None


# ── Repair Loop: Failure Path ─────────────────────────────────────────────────

@pytest.mark.asyncio
class TestRepairLoopFailed:
    async def test_exhausts_max_iterations(self, mock_db, mock_submission):
        """Loop should emit 'complete' with status=failed after max iterations."""

        lint_fail = _make_exec(stderr="Parse error: syntax error", exit_code=255)
        ai_resp = _make_ai_resp()
        boost_ctx = json.dumps({"schema_info": "", "docs_excerpts": [], "component_type": "model"})

        with (
            patch("api.services.repair_service.docker_service.create_container", AsyncMock(return_value=MagicMock())),
            patch("api.services.repair_service.docker_service.ping", AsyncMock(return_value=True)),
            patch("api.services.repair_service.docker_service.copy_code", AsyncMock()),
            patch("api.services.repair_service.docker_service.execute", AsyncMock(return_value=lint_fail)),
            patch("api.services.repair_service.docker_service.destroy", AsyncMock()),
            patch("api.services.repair_service.sandbox_service.setup_sqlite", AsyncMock()),
            patch("api.services.repair_service.sandbox_service.reinject_files", AsyncMock()),
            patch("api.services.repair_service.sandbox_service.inject_pest_test", AsyncMock()),
            patch("api.services.repair_service.boost_service.query_context", AsyncMock(return_value=boost_ctx)),
            patch("api.services.repair_service.ai_service.get_repair", AsyncMock(return_value=ai_resp)),
        ):
            events = await _collect(
                run_repair_loop("test-sub-id", "<?php class Broken {}", mock_db, max_iterations=2)
            )

        complete = next(e for e in events if e["event"] == "complete")
        assert complete["data"]["status"] == "failed"
        assert complete["data"]["iterations"] == 2


# ── Repair Loop: Mutation Gate ────────────────────────────────────────────────

@pytest.mark.asyncio
class TestRepairLoopMutationWeak:
    async def test_continues_when_mutation_score_low(self, mock_db, mock_submission):
        """When Pest passes but mutation score < 80%, loop should continue."""

        lint_ok = _make_exec(stdout="No syntax errors detected", exit_code=0)
        tinker_ok = _make_exec(stdout="CLASS_OK", exit_code=0)
        pest_fail = _make_exec(stdout="Tests: 1 failed", exit_code=1)
        pest_ok = _make_exec(stdout="Tests: 1 passed", exit_code=0)
        lint_fail = _make_exec(stderr="Fatal error", exit_code=1)
        ai_resp = _make_ai_resp()
        boost_ctx = json.dumps({"schema_info": "", "docs_excerpts": [], "component_type": "unknown"})

        mock_mut_weak = MutationResult(score=50.0, passed=False, output="Score: 50%", duration_ms=300)

        # Iteration 1: Pest fails -> AI fix (returns ai_resp.pest_test)
        # Iteration 2: Pest passes -> Mutation runs -> Mutation weak -> AI fix
        # Iteration 3: Lint fails -> AI loop exhausts
        iteration_count = [0]
        pest_count = [0]

        async def mock_execute(container, cmd, timeout=None, user=None):
            if "php -l" in cmd:
                iteration_count[0] += 1
                return lint_ok if iteration_count[0] < 3 else lint_fail
            return lint_ok

        async def mock_run_pest_test(container):
            pest_count[0] += 1
            return pest_fail if pest_count[0] == 1 else pest_ok

        with (
            patch("api.services.repair_service.docker_service.create_container", AsyncMock(return_value=MagicMock())),
            patch("api.services.repair_service.docker_service.ping", AsyncMock(return_value=True)),
            patch("api.services.repair_service.docker_service.copy_code", AsyncMock()),
            patch("api.services.repair_service.docker_service.execute", mock_execute),
            patch("api.services.repair_service.docker_service.destroy", AsyncMock()),
            patch("api.services.repair_service.sandbox_service.setup_sqlite", AsyncMock()),
            patch("api.services.repair_service.sandbox_service.reinject_files", AsyncMock()),
            patch("api.services.repair_service.sandbox_service.inject_pest_test", AsyncMock()),
            patch("api.services.repair_service.sandbox_service.detect_class_info", AsyncMock(return_value=_make_class_info())),
            patch("api.services.repair_service.sandbox_service.place_code_in_laravel", AsyncMock(return_value=tinker_ok)),
            patch("api.services.repair_service.sandbox_service.scaffold_route", AsyncMock()),
            patch("api.services.repair_service.sandbox_service.run_pest_test", mock_run_pest_test),
            patch("api.services.repair_service.sandbox_service.run_mutation_test", AsyncMock(return_value=mock_mut_weak)),
            patch("api.services.repair_service.boost_service.query_context", AsyncMock(return_value=boost_ctx)),
            patch("api.services.repair_service.ai_service.get_repair", AsyncMock(return_value=ai_resp)),
            patch("api.services.repair_service.context_service.retrieve_similar_repairs", AsyncMock(return_value="")),
        ):
            events = await _collect(
                run_repair_loop("test-sub-id", "<?php", mock_db, max_iterations=3)
            )

        mutation_events = [e for e in events if e["event"] == "mutation_result"]
        assert len(mutation_events) >= 1
        assert mutation_events[0]["data"]["passed"] is False
