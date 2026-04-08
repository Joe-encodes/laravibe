"""
mcp/server.py — MCP (Model Context Protocol) server for the repair platform.

Exposes one tool: repairLaravelApiCode
Call it from Cursor/Claude Code by adding this server to your MCP config.

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
import json
import os
import sys
import time
import httpx

REPAIR_API_URL = os.getenv("REPAIR_API_URL", "http://localhost:8000")
POLL_INTERVAL = 1.5   # seconds between status polls
MAX_WAIT = 600        # 10 min max


async def repair_laravel_api_code(code: str, max_iterations: int = 7) -> dict:
    """Submit code to the repair API and wait for the result."""
    async with httpx.AsyncClient(timeout=30) as client:
        # 1. Submit
        resp = await client.post(
            f"{REPAIR_API_URL}/api/repair",
            json={"code": code, "max_iterations": max_iterations},
        )
        resp.raise_for_status()
        submission_id = resp.json()["submission_id"]

        # 2. Poll until done
        deadline = time.monotonic() + MAX_WAIT
        while time.monotonic() < deadline:
            await asyncio.sleep(POLL_INTERVAL)
            status_resp = await client.get(f"{REPAIR_API_URL}/api/repair/{submission_id}")
            status_resp.raise_for_status()
            data = status_resp.json()

            if data["status"] in ("success", "failed"):
                last_iter = data["iterations"][-1] if data.get("iterations") else {}
                return {
                    "status": data["status"],
                    "submission_id": submission_id,
                    "iterations": data.get("total_iterations", 0),
                    "repaired_code": data.get("final_code", ""),
                    "diagnosis": last_iter.get("error_logs", "")[:500],
                    "mutation_score": last_iter.get("mutation_score"),
                }

        return {"status": "timeout", "submission_id": submission_id}


# ── Minimal JSON-RPC 2.0 MCP server (stdio transport) ─────────────────────────
async def handle_request(req: dict) -> dict:
    method = req.get("method", "")
    req_id = req.get("id")

    if method == "tools/list":
        return {
            "jsonrpc": "2.0", "id": req_id,
            "result": {
                "tools": [{
                    "name": "repairLaravelApiCode",
                    "description": (
                        "Submits broken PHP/Laravel REST API code to the AI repair platform. "
                        "Returns the repaired code, diagnosis, and iteration count."
                    ),
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "code": {"type": "string", "description": "Broken PHP/Laravel code"},
                            "max_iterations": {"type": "integer", "default": 7, "minimum": 1, "maximum": 10},
                        },
                        "required": ["code"],
                    },
                }]
            }
        }

    elif method == "tools/call":
        tool_name = req.get("params", {}).get("name", "")
        args = req.get("params", {}).get("arguments", {})

        if tool_name == "repairLaravelApiCode":
            try:
                result = await repair_laravel_api_code(
                    code=args["code"],
                    max_iterations=args.get("max_iterations", 7),
                )
                return {
                    "jsonrpc": "2.0", "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": json.dumps(result, indent=2)}]
                    }
                }
            except Exception as exc:
                return {
                    "jsonrpc": "2.0", "id": req_id,
                    "error": {"code": -32000, "message": str(exc)}
                }

    return {
        "jsonrpc": "2.0", "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"}
    }


async def main():
    """Read JSON-RPC requests from stdin, write responses to stdout."""
    while True:
        line = await asyncio.get_event_loop().run_in_executor(None, sys.stdin.readline)
        if not line:
            break
        try:
            req = json.loads(line.strip())
            resp = await handle_request(req)
            print(json.dumps(resp), flush=True)
        except json.JSONDecodeError:
            pass


if __name__ == "__main__":
    asyncio.run(main())
