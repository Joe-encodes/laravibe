"""
tests/integration/test_full_repair.py — End-to-end repair loop test.

Requires:
  - Docker daemon running
  - laravel-sandbox:latest image built
  - FastAPI running on localhost:8000 (or set REPAIR_API_URL env var)

Run with:
  pytest tests/integration/ --no-header -v

Skip automatically in CI unless INTEGRATION=1 is set.
"""
import os
import time
import pytest
import httpx

REPAIR_API = os.getenv("REPAIR_API_URL", "http://localhost:8000")
SKIP = not os.getenv("INTEGRATION")  # set INTEGRATION=1 to run

pytestmark = pytest.mark.skipif(SKIP, reason="Set INTEGRATION=1 to run integration tests")


TOKEN = os.getenv("REPAIR_TOKEN", "change-me-in-production")
AUTH_HEADERS = {"Authorization": f"Bearer {TOKEN}"}


def _submit_and_wait(code: str, max_iter: int = 4, timeout: int = 300) -> dict:
    """Submit code and poll until complete. Returns final submission dict."""
    with httpx.Client(timeout=30, headers=AUTH_HEADERS) as client:
        r = client.post(f"{REPAIR_API}/api/repair", json={"code": code, "max_iterations": max_iter})
        r.raise_for_status()
        sub_id = r.json()["submission_id"]

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            time.sleep(3)
            status = client.get(f"{REPAIR_API}/api/repair/{sub_id}").json()
            if status["status"] in ("success", "failed"):
                return status

        pytest.fail(f"Repair timed out after {timeout}s")


@pytest.fixture(scope="module")
def api_health():
    """Verify the API is reachable before running any integration tests."""
    try:
        r = httpx.get(f"{REPAIR_API}/api/health", timeout=5)
        assert r.status_code == 200
    except Exception as exc:
        pytest.skip(f"API not reachable at {REPAIR_API}: {exc}")


class TestMissingModelFixture:
    def test_missing_model_repaired(self, api_health):
        code = open("tests/fixtures/missing_model.php").read()
        result = _submit_and_wait(code)
        assert result["status"] == "success", (
            f"Expected success, got {result['status']}. "
            f"Summary: {result.get('error_summary')}"
        )
        last_iter = result["iterations"][-1] if result.get("iterations") else {}
        assert last_iter.get("mutation_score", 0) >= 80, (
            f"Mutation score too low: {last_iter.get('mutation_score')}"
        )


class TestWrongNamespaceFixture:
    def test_wrong_namespace_repaired(self, api_health):
        code = open("tests/fixtures/wrong_namespace.php").read()
        result = _submit_and_wait(code)
        assert result["status"] == "success"


class TestMissingImportFixture:
    def test_missing_import_repaired(self, api_health):
        code = open("tests/fixtures/missing_import.php").read()
        result = _submit_and_wait(code)
        assert result["status"] == "success"


class TestEvaluateEndpoint:
    def test_evaluate_returns_results(self, api_health):
        """The /api/evaluate endpoint should run all samples and return a report."""
        with httpx.Client(timeout=600) as client:
            r = client.get(f"{REPAIR_API}/api/evaluate", headers=AUTH_HEADERS)
            assert r.status_code == 200
            data = r.json()
            assert "success_rate_pct" in data
            assert data["total_cases"] >= 0
