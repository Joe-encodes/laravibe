"""
tests/integration/test_live_api.py — Live integration tests against the running server.

Run with:
    pytest tests/integration/test_live_api.py -vv --timeout=30

Requires the server to be running: uvicorn api.main:app --port 8000
"""
import time
import httpx
import pytest

BASE_URL = "http://localhost:8000"
TOKEN = "laravibe-repair-2026-safe-token"
AUTH_HEADER = {"Authorization": f"Bearer {TOKEN}"}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _client() -> httpx.Client:
    return httpx.Client(base_url=BASE_URL, timeout=20.0)


# ---------------------------------------------------------------------------
# Health & Root
# ---------------------------------------------------------------------------

class TestHealth:
    def test_root_returns_message(self):
        with _client() as c:
            r = c.get("/")
        assert r.status_code == 200
        assert "Laravel AI Repair Platform" in r.json()["message"]

    def test_health_endpoint_all_green(self):
        with _client() as c:
            r = c.get("/api/health")
        data = r.json()
        assert r.status_code == 200
        assert data["status"] == "ok"
        assert data["docker"] == "connected", f"Docker not connected: {data['docker']}"
        assert data["db"] == "connected", f"DB not connected: {data['db']}"

    def test_redis_is_reachable(self):
        """Indirect test: if the server started without crashing, Redis pool is OK."""
        with _client() as c:
            r = c.get("/api/health")
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Stats (unauthenticated should 401/403, authenticated should 200)
# ---------------------------------------------------------------------------

class TestStats:
    def test_stats_summary_requires_auth(self):
        with _client() as c:
            r = c.get("/api/stats/summary")
        assert r.status_code in (401, 403)

    def test_stats_summary_with_auth(self):
        with _client() as c:
            r = c.get("/api/stats/summary", headers=AUTH_HEADER)
        assert r.status_code == 200
        data = r.json()
        assert "overall" in data
        assert "categories" in data
        assert "total" in data

    def test_stats_unified_with_auth(self):
        with _client() as c:
            r = c.get("/api/stats/", headers=AUTH_HEADER)
        assert r.status_code == 200
        data = r.json()
        assert "global_success_rate" in data
        assert "avg_iterations" in data
        assert "total_repairs" in data
        assert "status_distribution" in data

    def test_stats_efficiency_with_auth(self):
        with _client() as c:
            r = c.get("/api/stats/efficiency", headers=AUTH_HEADER)
        assert r.status_code == 200
        assert "trends" in r.json()

    def test_stats_export_csv(self):
        # CSV export can be slow with many records; give it more time
        with httpx.Client(base_url=BASE_URL, timeout=45.0) as c:
            r = c.get("/api/stats/export?limit=10", headers=AUTH_HEADER)
        assert r.status_code == 200
        assert "text/csv" in r.headers["content-type"]
        assert "submission_id" in r.text  # CSV header row


# ---------------------------------------------------------------------------
# Repair endpoint — validation & submission
# ---------------------------------------------------------------------------

class TestRepairEndpoint:
    def test_repair_requires_auth(self):
        with _client() as c:
            r = c.post("/api/repair", json={"code": "<?php", "prompt": "test"})
        assert r.status_code in (401, 403)

    def test_repair_rejects_oversized_code(self):
        """Code > max_code_size_kb should be rejected with 400."""
        big_code = "<?php " + ("// comment\n" * 10_000)
        with _client() as c:
            r = c.post("/api/repair", json={"code": big_code}, headers=AUTH_HEADER)
        assert r.status_code == 400

    def test_repair_accepts_valid_submission(self):
        """A valid submission should be accepted with 202 and return a submission_id."""
        code = "<?php\nnamespace App\\Http\\Controllers;\nuse App\\Models\\User;\nclass UserController extends Controller {\n    public function index() { return User::all(); }\n}"
        with _client() as c:
            r = c.post("/api/repair", json={"code": code, "prompt": "Fix N+1 query"}, headers=AUTH_HEADER)
        assert r.status_code == 202
        data = r.json()
        assert "submission_id" in data
        assert len(data["submission_id"]) == 36  # UUID length

    def test_repair_get_status(self):
        """After submission, GET /api/repair/{id} should return the submission status."""
        code = "<?php echo 'hello';"
        with _client() as c:
            post_r = c.post("/api/repair", json={"code": code}, headers=AUTH_HEADER)
            assert post_r.status_code == 202
            sub_id = post_r.json()["submission_id"]

            # Poll for up to 5 seconds
            for _ in range(5):
                get_r = c.get(f"/api/repair/{sub_id}")
                assert get_r.status_code == 200
                assert get_r.json()["id"] == sub_id
                time.sleep(1)

    def test_repair_get_nonexistent_returns_404(self):
        with _client() as c:
            r = c.get("/api/repair/00000000-0000-0000-0000-000000000000")
        assert r.status_code == 404

    def test_stream_endpoint_auth_check(self):
        """SSE stream endpoint should reject missing/bad tokens."""
        with _client() as c:
            r = c.get("/api/repair/some-id/stream")  # no token
        assert r.status_code in (401, 422)  # missing query param

    def test_stream_endpoint_invalid_token(self):
        with _client() as c:
            r = c.get("/api/repair/some-id/stream?token=WRONG_TOKEN")
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# History endpoint
# ---------------------------------------------------------------------------

class TestHistory:
    def test_history_requires_auth(self):
        """History endpoint must reject unauthenticated requests."""
        with _client() as c:
            r = c.get("/api/history")
        # The server returns 401 or 403 — not 200
        assert r.status_code in (401, 403), (
            f"Expected 401/403 but got {r.status_code}. "
            "History route is missing auth guard!"
        )

    def test_history_returns_list(self):
        with _client() as c:
            r = c.get("/api/history", headers=AUTH_HEADER)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, (list, dict))
