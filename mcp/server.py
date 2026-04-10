"""
mcp/server.py — MCP (Model Context Protocol) server for the repair platform.

Exposes one tool: repair_laravel_code
Uses the official FastMCP SDK which handles the initialize/initialized handshake
and all JSON-RPC 2.0 protocol details automatically.

Usage in Cursor .cursor/mcp.json:
{
  "laravel-repair": {
    "command": "python",
    "args": ["mcp/server.py"],
    "env": { "REPAIR_API_URL": "http://localhost:8000" }
  }
}
"""
import asyncio
import os
import time

import httpx
from mcp.server.fastmcp import FastMCP

REPAIR_API_URL = os.getenv("REPAIR_API_URL", "http://localhost:8000")
POLL_INTERVAL_SECONDS = 1.5
MAX_WAIT_SECONDS = 600  # 10 min max

mcp = FastMCP(
    "Laravel AI Repair",
    description=(
        "Submits broken PHP/Laravel REST API code to the AI repair platform. "
        "Returns the repaired code, diagnosis, and iteration count."
    ),
)


@mcp.tool()
async def repair_laravel_code(code: str, max_iterations: int = 7) -> str:
    """Submit broken PHP/Laravel code for automated repair.

    The platform runs the code in a Docker sandbox, diagnoses errors using
    Laravel Boost context, applies AI-generated fixes, and validates with
    Pest tests + mutation testing. Repeats up to max_iterations times.

    Args:
        code: The broken PHP/Laravel code to repair.
        max_iterations: Maximum repair iterations (1-10, default 7).

    Returns:
        JSON string with repair results including status, repaired code,
        diagnosis, iteration count, and mutation score.
    """
    import json

    async with httpx.AsyncClient(timeout=30) as client:
        # 1. Submit the code
        resp = await client.post(
            f"{REPAIR_API_URL}/api/repair",
            json={"code": code, "max_iterations": max_iterations},
        )
        resp.raise_for_status()
        submission_id = resp.json()["submission_id"]

        # 2. Poll until done
        deadline = time.monotonic() + MAX_WAIT_SECONDS
        while time.monotonic() < deadline:
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
            status_resp = await client.get(
                f"{REPAIR_API_URL}/api/repair/{submission_id}"
            )
            status_resp.raise_for_status()
            data = status_resp.json()

            if data["status"] in ("success", "failed"):
                last_iter = data["iterations"][-1] if data.get("iterations") else {}
                result = {
                    "status": data["status"],
                    "submission_id": submission_id,
                    "iterations": data.get("total_iterations", 0),
                    "repaired_code": data.get("final_code", ""),
                    "diagnosis": last_iter.get("error_logs", "")[:500],
                    "mutation_score": last_iter.get("mutation_score"),
                }
                return json.dumps(result, indent=2)

        return json.dumps({"status": "timeout", "submission_id": submission_id})


if __name__ == "__main__":
    mcp.run()
