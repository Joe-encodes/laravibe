"""
MCP server end-to-end smoke test.

Exercises the repair_laravel_code tool flow against the live local API:
  1. Logs in with the master token to obtain a JWT session token.
  2. Submits intentionally broken PHP/Laravel code.
  3. Polls until complete (success / failed / timeout).
  4. Prints the result in the same JSON shape the MCP tool would return.
"""
import asyncio
import json
import os
import time

import httpx

REPAIR_API_URL  = os.getenv("REPAIR_API_URL",  "http://127.0.0.1:8000")
MASTER_TOKEN    = os.getenv("MASTER_REPAIR_TOKEN", "laravibe-repair-2026-safe-token")

POLL_INTERVAL   = 2.0   # seconds between status checks
MAX_WAIT        = 300   # 5-minute cap

# ── Intentionally broken Laravel model ───────────────────────────────────────
BROKEN_CODE = """<?php

namespace App\\Models;

use Illuminate\\Database\\Eloquent\\Model;

class Product extends Model
{
    // BUG 1: no $fillable array — causes MassAssignmentException
    // BUG 2: missing semicolon — syntax error
    public function getPrice()
    {
        return $this->price * 1.1
    }
}
"""


async def login(client: httpx.AsyncClient) -> str:
    """Exchange the master token for a short-lived JWT session token."""
    resp = await client.post(
        f"{REPAIR_API_URL}/api/auth/login",
        json={"token": MASTER_TOKEN},
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


async def run() -> None:
    print("=" * 62)
    print("  LaraVibe MCP — End-to-End Smoke Test")
    print("=" * 62)

    async with httpx.AsyncClient(timeout=30) as client:

        # ── 0. Authenticate ───────────────────────────────────────
        print("\n[0/3] Authenticating with master token …")
        jwt = await login(client)
        headers = {"Authorization": f"Bearer {jwt}"}
        print(f"      JWT acquired ({len(jwt)} chars)")

        # ── 1. Submit broken code ─────────────────────────────────
        print("\n[1/3] Submitting broken PHP code to /api/repair …")
        resp = await client.post(
            f"{REPAIR_API_URL}/api/repair",
            json={"code": BROKEN_CODE, "max_iterations": 3},
            headers=headers,
        )
        resp.raise_for_status()
        sid = resp.json()["submission_id"]
        print(f"      submission_id = {sid}")

        # ── 2. Poll for completion ────────────────────────────────
        print("\n[2/3] Polling for completion …")
        deadline = time.monotonic() + MAX_WAIT
        data: dict = {}
        while time.monotonic() < deadline:
            await asyncio.sleep(POLL_INTERVAL)
            sr = await client.get(
                f"{REPAIR_API_URL}/api/repair/{sid}",
                headers=headers,
            )
            sr.raise_for_status()
            data = sr.json()
            status = data.get("status", "pending")
            iters  = data.get("total_iterations", 0)
            print(f"      status={status:<10} iterations={iters}", end="\r", flush=True)
            if status in ("success", "failed"):
                print()  # clear carriage-return line
                break
        else:
            print("\n      ⚠  Timed out waiting for repair.")

        # ── 3. Report results ─────────────────────────────────────
        print("\n[3/3] Results")
        final_status = data.get("status", "unknown")
        total_iters  = data.get("total_iterations", 0)
        repaired     = data.get("final_code", "")
        last_iter    = (data.get("iterations") or [{}])[-1]
        mutation     = last_iter.get("mutation_score", "n/a")

        print(f"      Status          : {final_status}")
        print(f"      Iterations used : {total_iters}")
        print(f"      Mutation score  : {mutation}")

        if repaired:
            print("\n── Repaired code (first 600 chars) ──────────────────")
            print(repaired[:600])

        # Simulate what the MCP tool returns to the AI agent
        mcp_result = {
            "status": final_status,
            "submission_id": sid,
            "iterations": total_iters,
            "repaired_code": repaired,
            "diagnosis": last_iter.get("error_logs", "")[:500],
            "mutation_score": mutation,
        }
        print("\n── MCP JSON payload (as tool would return it) ───────")
        print(json.dumps(mcp_result, indent=2)[:1500])

        print("\n" + "=" * 62)
        icon = "✅" if final_status == "success" else "❌"
        print(f"  {icon}  Smoke test complete — {final_status.upper()}")
        print("=" * 62)


if __name__ == "__main__":
    asyncio.run(run())
