import pytest
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch
from api.models import Iteration, Submission
from api.services.repair.orchestrator import run_repair_loop
from api.services.ai_service import AIRepairResponse, PatchSpec
from api.services.sandbox.laravel import ClassInfo
from api.services.error_classifier import ClassifiedError

@pytest.fixture
def mock_db():
    db = AsyncMock()
    submission = MagicMock(spec=Submission)
    submission.id = "test-id"
    submission.status = "pending"
    submission.is_cancelled = False
    submission.container_id = None
    
    res = MagicMock()
    res.scalar_one = MagicMock(return_value=submission)
    res.scalars = MagicMock(return_value=MagicMock(first=MagicMock(return_value=submission)))
    
    db.execute = AsyncMock(return_value=res)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.rollback = AsyncMock()
    
    async def mock_refresh(obj):
        pass
    db.refresh.side_effect = mock_refresh
    
    return db

@pytest.fixture
def orchestrator_mocks(mocker):
    mocks = {
        "sandbox": mocker.patch("api.services.repair.orchestrator.sandbox"),
        "boost": mocker.patch("api.services.repair.orchestrator.boost_service"),
        "context": mocker.patch("api.services.repair.orchestrator.context"),
        "classifier": mocker.patch("api.services.repair.orchestrator.classify_error"),
        "pipeline": mocker.patch("api.services.repair.orchestrator.pipeline"),
        "patch_service": mocker.patch("api.services.repair.orchestrator.patch_service"),
        "escalation": mocker.patch("api.services.repair.orchestrator.escalation_service"),
        "ai_service": mocker.patch("api.services.repair.orchestrator.ai_service"),
        "discovery": mocker.patch("api.services.repair.orchestrator.discovery"),
    }
    
    mocks["sandbox"].create_sandbox = AsyncMock()
    mocks["sandbox"].setup_sqlite = AsyncMock()
    mocks["sandbox"].detect_class_info = AsyncMock()
    mocks["sandbox"].place_code_in_laravel = AsyncMock()
    mocks["sandbox"].scaffold_route = AsyncMock()
    mocks["sandbox"].execute_code = AsyncMock()
    mocks["sandbox"].read_file = AsyncMock()
    mocks["sandbox"].write_file = AsyncMock()
    mocks["sandbox"].lint_php = AsyncMock()
    mocks["sandbox"].run_pest_test = AsyncMock()
    mocks["sandbox"].run_phpstan = AsyncMock()
    mocks["sandbox"].run_mutation_test = AsyncMock()
    mocks["sandbox"].capture_laravel_log = AsyncMock()
    mocks["sandbox"].destroy_sandbox = AsyncMock()
    mocks["sandbox"].get_container = MagicMock()  # Synchronous
    
    mocks["boost"].get_boost_context = AsyncMock()
    mocks["context"].store_repair_success = AsyncMock()
    mocks["context"].get_similar_repairs = AsyncMock()
    mocks["escalation"].escalate_empty_patch = AsyncMock()
    mocks["patch_service"].apply_all = AsyncMock()
    mocks["ai_service"].get_post_mortem = AsyncMock()
    mocks["discovery"].discover_referenced_signatures = AsyncMock()
    
    mocks["docker"] = mocker.patch("api.services.sandbox.docker")
    mocks["docker"]._get_client = MagicMock()
    mocks["docker"]._get_client().ping = MagicMock()
    mocks["docker"].copy_code = AsyncMock()
    mocks["docker"].execute = AsyncMock()
    
    return mocks

@pytest.mark.anyio
class TestOrchestrator:

    async def _collect_events(self, gen):
        events = []
        async for evt in gen:
            events.append(evt)
        return events

    def _make_ai_resp(self, patches=None):
        return AIRepairResponse(
            thought_process="Thinking",
            diagnosis="Diag",
            fix_description="Fixing",
            patches=patches or [],
            pest_test="it('works')",
            raw="raw output",
            prompt="prompt",
            model_used="test-model"
        )

    def _make_class_info(self):
        return ClassInfo(
            namespace="App/Http/Controllers",
            clean_namespace="App\\Http\\Controllers",
            classname="A",
            dest_file="app/Http/Controllers/A.php",
            fqcn="App\\Http\\Controllers\\A",
            route_resource="a"
        )

    async def test_success_path(self, mock_db, orchestrator_mocks):
        orchestrator_mocks["sandbox"].create_sandbox.return_value = "container-id"
        orchestrator_mocks["sandbox"].execute_code.return_value = {"output": "Error", "exit_code": 1}
        orchestrator_mocks["classifier"].side_effect = [
            ClassifiedError("MISSING_METHOD", "sum", {}, ""),
            ClassifiedError("none", "Clear", {}, "")
        ]
        
        ai_resp = self._make_ai_resp([
            PatchSpec(action="full_replace", target="app/A.php", replacement="...", filename="A.php")
        ])
        
        async def mock_run_pipeline(*args, **kwargs):
            yield "ai_thinking", {"role": "Planner"}
            yield "final_result", (ai_resp, {"planner": "m1"})
            
        orchestrator_mocks["pipeline"].run_pipeline.side_effect = mock_run_pipeline
        orchestrator_mocks["sandbox"].detect_class_info.return_value = self._make_class_info()
        orchestrator_mocks["sandbox"].place_code_in_laravel.return_value = True
        orchestrator_mocks["sandbox"].lint_php.return_value = (True, "")
        orchestrator_mocks["sandbox"].run_pest_test.return_value = {"success": True, "output": "OK"}
        orchestrator_mocks["sandbox"].run_mutation_test.return_value = MagicMock(passed=True, score=100)
        orchestrator_mocks["boost"].get_boost_context.return_value = "{}"
        orchestrator_mocks["context"].get_similar_repairs.return_value = []
        
        events = await self._collect_events(run_repair_loop("test-id", "code", "prompt", mock_db))
        assert any(e["event"] == "complete" and e["data"]["status"] == "success" for e in events)

    async def test_zero_patches_escalate(self, mock_db, orchestrator_mocks):
        orchestrator_mocks["sandbox"].create_sandbox.return_value = "cid"
        orchestrator_mocks["sandbox"].execute_code.return_value = {"output": "Err" * 100, "exit_code": 1}
        orchestrator_mocks["classifier"].return_value = ClassifiedError("UNKNOWN", "sum", {}, "")
        
        ai_resp = self._make_ai_resp(patches=[])
        async def mock_run_pipeline(*args, **kwargs):
            yield "final_result", (ai_resp, {})
        orchestrator_mocks["pipeline"].run_pipeline.side_effect = mock_run_pipeline
        orchestrator_mocks["sandbox"].detect_class_info.return_value = self._make_class_info()
        orchestrator_mocks["boost"].get_boost_context.return_value = "{}"
        orchestrator_mocks["context"].get_similar_repairs.return_value = []

        events = await self._collect_events(run_repair_loop("test-id", "code", "p", mock_db, max_iterations=2))
        
        starts = [e for e in events if e["event"] == "iteration_start"]
        assert len(starts) == 2
        
        comp = [e for e in events if e["event"] == "complete"][0]
        assert comp["data"]["status"] == "failed"

    async def test_pest_syntax_error_retry(self, mock_db, orchestrator_mocks):
        orchestrator_mocks["sandbox"].create_sandbox.return_value = "cid"
        orchestrator_mocks["sandbox"].execute_code.return_value = {"output": "Err" * 100, "exit_code": 1}
        orchestrator_mocks["classifier"].return_value = ClassifiedError("MISSING_METHOD", "sum", {}, "")
        
        ai_resp = self._make_ai_resp([PatchSpec("full_replace", "app/A.php", "r", "A.php")])
        async def mock_run_pipeline(*args, **kwargs):
            yield "final_result", (ai_resp, {})
        orchestrator_mocks["pipeline"].run_pipeline.side_effect = mock_run_pipeline
        orchestrator_mocks["sandbox"].detect_class_info.return_value = self._make_class_info()
        orchestrator_mocks["sandbox"].lint_php.return_value = (True, "")
        orchestrator_mocks["patch_service"].apply_all.return_value = {"app/A.php": True}
        
        orchestrator_mocks["sandbox"].run_pest_test.side_effect = [
            {"success": False, "output": "PHP Parse error: ..."},
            {"success": True, "output": "OK"}
        ]
        orchestrator_mocks["sandbox"].run_mutation_test.return_value = MagicMock(passed=True, score=90)
        orchestrator_mocks["boost"].get_boost_context.return_value = "{}"
        orchestrator_mocks["context"].get_similar_repairs.return_value = []

        events = await self._collect_events(run_repair_loop("test-id", "code", "p", mock_db, max_iterations=2))
        
        starts = [e for e in events if e["event"] == "iteration_start"]
        assert len(starts) == 2
        comp = [e for e in events if e["event"] == "complete" and e["data"]["status"] == "success"]
        assert len(comp) > 0

    async def test_phpstan_failure_logged(self, mock_db, orchestrator_mocks):
        orchestrator_mocks["sandbox"].create_sandbox.return_value = "cid"
        orchestrator_mocks["sandbox"].execute_code.return_value = {"output": "Err" * 100, "exit_code": 1}
        orchestrator_mocks["classifier"].return_value = ClassifiedError("TYPE_ERROR", "sum", {}, "")
        
        ai_resp = self._make_ai_resp([PatchSpec("full_replace", "app/A.php", "r", "A.php")])
        async def mock_run_pipeline(*args, **kwargs):
            yield "final_result", (ai_resp, {})
        orchestrator_mocks["pipeline"].run_pipeline.side_effect = mock_run_pipeline
        orchestrator_mocks["sandbox"].detect_class_info.return_value = self._make_class_info()
        
        orchestrator_mocks["sandbox"].lint_php.return_value = (True, "")
        orchestrator_mocks["patch_service"].apply_all.return_value = {"app/A.php": True}
        orchestrator_mocks["sandbox"].run_phpstan.return_value = {"success": False, "output": "PHPStan error"}
        
        orchestrator_mocks["boost"].get_boost_context.return_value = "{}"
        orchestrator_mocks["context"].get_similar_repairs.return_value = []
        
        events = await self._collect_events(run_repair_loop("test-id", "code", "p", mock_db, max_iterations=1))
        # Ensure we wait for the loop to process
        assert any(e["event"] == "phpstan_result" for e in events)

    async def test_mutation_failure_logged(self, mock_db, orchestrator_mocks):
        orchestrator_mocks["sandbox"].create_sandbox.return_value = "cid"
        orchestrator_mocks["sandbox"].execute_code.return_value = {"output": "Err" * 100, "exit_code": 1}
        orchestrator_mocks["classifier"].return_value = ClassifiedError("LOGIC_ERROR", "sum", {}, "")
        
        ai_resp = self._make_ai_resp([PatchSpec("full_replace", "app/A.php", "r", "A.php")])
        async def mock_run_pipeline(*args, **kwargs):
            yield "final_result", (ai_resp, {})
        orchestrator_mocks["pipeline"].run_pipeline.side_effect = mock_run_pipeline
        orchestrator_mocks["sandbox"].detect_class_info.return_value = self._make_class_info()
        
        orchestrator_mocks["sandbox"].lint_php.return_value = (True, "")
        orchestrator_mocks["patch_service"].apply_all.return_value = {"app/A.php": True}
        orchestrator_mocks["sandbox"].run_pest_test.return_value = {"success": True, "output": "OK"}
        orchestrator_mocks["sandbox"].run_mutation_test.return_value = MagicMock(passed=False, score=45)
        
        orchestrator_mocks["boost"].get_boost_context.return_value = "{}"
        orchestrator_mocks["context"].get_similar_repairs.return_value = []
        
        events = await self._collect_events(run_repair_loop("test-id", "code", "p", mock_db, max_iterations=1))
        assert any(e["event"] == "mutation_result" for e in events)

    async def test_job_cancellation(self, mock_db, orchestrator_mocks):
        orchestrator_mocks["sandbox"].create_sandbox.return_value = "cid"
        async def mock_refresh(obj):
            obj.is_cancelled = True
        mock_db.refresh.side_effect = mock_refresh
        
        events = await self._collect_events(run_repair_loop("test-id", "code", "p", mock_db))
        comp = [e for e in events if e["event"] == "complete"]
        assert len(comp) > 0
        assert comp[0]["data"]["status"] == "cancelled"
