#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# verify_resilience.sh — Proof of Container Resilience (Phase 1)
# Verifies that long-running commands return 124 (TIMEOUT) but don't kill the container.
# ─────────────────────────────────────────────────────────────────────────────

# Helper to check if API is running
if ! curl -s http://localhost:8000/api/health > /dev/null; then
    echo "❌ Error: FastAPI server not running on localhost:8000"
    exit 1
fi

echo "▶ Phase 1: Creating a test iteration..."
# We use a small python script to trigger the docker_service.execute directly via a mock if needed,
# but here we'll use a real API call and check logs.

# Alternatively, we create a specialized test endpoint for verification
cat <<EOF > api/routers/verify.py
from fastapi import APIRouter
from api.services import docker_service
import asyncio

router = APIRouter(prefix="/api/verify", tags=["verify"])

@router.get("/resilience")
async def test_resilience():
    container = await docker_service.create_container()
    try:
        # Run a command that takes 10s with a 5s timeout
        result = await docker_service.execute(container, "sleep 10", timeout=5)
        
        # Check if container is still alive
        alive = await docker_service.is_alive(container)
        
        return {
            "timeout_detected": result.exit_code == 124,
            "container_still_alive": alive,
            "status": "PASS" if (result.exit_code == 124 and alive) else "FAIL"
        }
    finally:
        await docker_service.destroy(container)
EOF

echo "   ✅ Verification endpoint created in api/routers/verify.py"
echo "▶ Restart the server to pick up the new route, then run:"
echo "   curl http://localhost:8000/api/verify/resilience"
