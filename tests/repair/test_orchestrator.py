
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from api.services.repair.orchestrator import run_repair_loop
from api.models import Iteration
from api.services.ai_service import AIRepairResponse, PatchSpec
from api.services.sandbox.laravel import ClassInfo


@pytest.fixture
def mock_db():
    db = AsyncMock()
    submission = MagicMock()
    submission.id = "test-id"
    submission.status = "pending"
    db.execute = AsyncMock(return_value=MagicMock(scalar_one=lambda: submission))
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


@pytest.fixture
def fake_class_info():
    return ClassInfo(
        namespace="App/Http/Controllers",
        clean_namespace="App\\Http\\Controllers",
        classname="UserController",
        dest_file="/var/www/sandbox/app/Http/Controllers/UserController.php",
        fqcn="App\\Http\\Controllers\\UserController",
        route_resource="users",
    )


async def _collect(gen):
    events = []
    async for evt in gen:
        events.append(evt)
    return events


@pytest.mark.asyncio
class TestOrchestrator:
    async def test_success_path(self, mock_db, fake_class_info):
        """Full happy path: env setup → AI → patch → Pest → success."""
        ai_resp = AIRepairResponse(
            thought_process="Fix the import.",
            diagnosis="Missing use statement",
            fix_description="Added use App\\Models\\User",
            patches=[PatchSpec(
                action="full_replace",
                target="app/Http/Controllers/UserController.php",
                replacement="<?php",
                filename="app/Http/Controllers/UserController.php",
            )],
            pest_test="<?php it('works');",
            raw="<repair>...</repair>",
            prompt="prompt",
            model_used="mock-model",
        )

        with (
            patch("api.services.sandbox.create_sandbox", AsyncMock(return_value="container-1")),
            patch("api.services.sandbox.get_container", MagicMock(return_value=MagicMock())),
            patch("api.services.sandbox.docker.copy_code", AsyncMock()),
            patch("api.services.sandbox.setup_sqlite", AsyncMock()),
            patch("api.services.sandbox.detect_class_info", AsyncMock(return_value=fake_class_info)),
            patch("api.services.sandbox.place_code_in_laravel", AsyncMock(return_value=True)),
            patch("api.services.sandbox.scaffold_route", AsyncMock()),
            patch("api.services.sandbox.execute_code", AsyncMock(return_value={"output": "Class not found"})),
            patch("api.services.boost_service.get_boost_context", AsyncMock(return_value="## Schema\nusers table")),
            patch("api.services.repair.context.get_similar_repairs", AsyncMock(return_value="")),
            patch("api.services.repair.pipeline.run_pipeline", AsyncMock(return_value=(ai_resp, {"planner": "m"}))),
            patch("api.services.patch_service.apply_all", AsyncMock(return_value={"app/Http/Controllers/UserController.php": True})),
            patch("api.services.sandbox.run_phpstan", AsyncMock(return_value={"success": True, "output": ""})),
            patch("api.services.sandbox.prepare_pest_test", return_value="<?php it('works');"),
            patch("api.services.sandbox.run_pest_test", AsyncMock(return_value={"success": True, "output": "1 passed"})),
            patch("api.services.sandbox.run_mutation_test", AsyncMock(return_value=MagicMock(score=85.0, passed=True))),
            patch("api.services.sandbox.read_file", AsyncMock(return_value="<?php fixed")),
            patch("api.services.sandbox.destroy_sandbox", AsyncMock()),
        ):
            events = await _collect(run_repair_loop("test-id", "<?php", None, mock_db))

        types = {e["type"] for e in events}
        assert "repair_success" in types
        assert "patch_applied" in types
        assert "context_gathered" in types

    async def test_zero_patches_escalates(self, mock_db, fake_class_info):
        """When AI returns no patches, the loop should break and emit an error."""
        ai_resp = AIRepairResponse(
            thought_process=None, diagnosis="Stumped", fix_description="",
            patches=[], pest_test="", raw="<repair/>", prompt="", model_used="mock",
        )

        with (
            patch("api.services.sandbox.create_sandbox", AsyncMock(return_value="container-1")),
            patch("api.services.sandbox.get_container", MagicMock(return_value=MagicMock())),
            patch("api.services.sandbox.setup_sqlite", AsyncMock()),
            patch("api.services.sandbox.detect_class_info", AsyncMock(return_value=fake_class_info)),
            patch("api.services.sandbox.place_code_in_laravel", AsyncMock(return_value=True)),
            patch("api.services.sandbox.scaffold_route", AsyncMock()),
            patch("api.services.sandbox.execute_code", AsyncMock(return_value={"output": "error"})),
            patch("api.services.boost_service.get_boost_context", AsyncMock(return_value="")),
            patch("api.services.repair.context.get_similar_repairs", AsyncMock(return_value="")),
            patch("api.services.repair.pipeline.run_pipeline", AsyncMock(return_value=(ai_resp, {}))),
            patch("api.services.escalation_service.escalate_empty_patch", AsyncMock()),
            patch("api.services.sandbox.destroy_sandbox", AsyncMock()),
        ):
            events = await _collect(run_repair_loop("test-id", "<?php", None, mock_db))

        assert any(e["type"] == "error" for e in events)
        assert not any(e["type"] == "repair_success" for e in events)
