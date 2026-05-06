#!/usr/bin/env python3
"""
live_test_runner.py — Fire all 5 dataset cases against the live server
and report pass/fail with full SSE event streaming.

Key facts about this server's SSE implementation:
  - Token goes as query-param:  ?token=...  (NOT Authorization header)
    because the browser's EventSource can't set custom headers.
  - Each SSE data line is a single JSON object:
      data: {"event": "log_line", "data": {"msg": "..."}}
  - POST /api/repair DOES use Authorization: Bearer ...

Usage:
    ./venv/bin/python3 live_test_runner.py          # all 5 cases
    ./venv/bin/python3 live_test_runner.py case-001  # single case
"""
import asyncio
import httpx
import json
import sys
import os
import time

from dotenv import load_dotenv
load_dotenv()

BASE_URL   = "http://127.0.0.1:8000"
TOKEN      = os.environ.get("MASTER_REPAIR_TOKEN", "change-me-in-production")
DATASET_DIR = "dataset"

CASES = ["case-001", "case-002", "case-003", "case-004", "case-005"]

PASS = "\u2705"
FAIL = "\u274c"


def load_code(case: str) -> str:
    path = os.path.join(DATASET_DIR, case, "code.php")
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


async def get_session_token(client: httpx.AsyncClient) -> str:
    resp = await client.post(f"{BASE_URL}/api/auth/login", json={"token": TOKEN})
    if resp.status_code != 200:
        raise RuntimeError(f"Login failed: {resp.text}")
    return resp.json()["access_token"]


async def submit_repair(client: httpx.AsyncClient, case: str, code: str, jwt_token: str) -> str:
    """POST /api/repair — returns submission_id."""
    payload = {
        "code": code,
        "prompt": f"Fix all bugs in this PHP/Laravel code. Test case: {case}",
        "max_iterations": 4,
        "use_boost": True,
        "use_mutation_gate": True,
    }
    resp = await client.post(
        f"{BASE_URL}/api/repair",
        json=payload,
        headers={"Authorization": f"Bearer {jwt_token}"},
        timeout=30,
    )
    if resp.status_code != 202:
        raise RuntimeError(f"POST /api/repair returned {resp.status_code}: {resp.text[:200]}")
    return resp.json()["submission_id"]


async def stream_events(sub_id: str, case: str, jwt_token: str) -> dict:
    """
    Consume the SSE stream at /api/repair/{id}/stream?token=...
    Returns a summary dict when the 'complete' event arrives.
    """
    url = f"{BASE_URL}/api/repair/{sub_id}/stream?token={jwt_token}"
    summary = {
        "case": case,
        "submission_id": sub_id,
        "status": "unknown",
        "iterations": 0,
        "mutation_score": None,
        "pest_pass": False,
        "errors": [],
    }

    start = time.monotonic()

    # httpx streaming with a long timeout for the full repair
    async with httpx.AsyncClient(timeout=httpx.Timeout(900, connect=10)) as stream_client:
        async with stream_client.stream("GET", url) as resp:
            if resp.status_code not in (200, 202):
                raise RuntimeError(f"Stream returned {resp.status_code}")

            async for raw_line in resp.aiter_lines():
                raw_line = raw_line.strip()

                # Skip blank lines and heartbeat pings (": ping")
                if not raw_line or raw_line.startswith(":"):
                    continue

                # SSE lines start with "data: "
                if not raw_line.startswith("data:"):
                    continue

                payload_str = raw_line[5:].strip()
                try:
                    envelope = json.loads(payload_str)
                except json.JSONDecodeError:
                    continue

                event = envelope.get("event", "")
                data  = envelope.get("data", {})

                # ── Pretty-print each event ──────────────────────────────────
                if event == "iteration_start":
                    print(f"\n    \U0001f501 Iteration {data.get('iteration')}/{data.get('max')}")

                elif event == "log_line":
                    print(f"    > {data.get('msg', '')}")

                elif event == "ai_thinking" and "diagnosis" in data:
                    diag = (data.get("diagnosis") or "")[:90]
                    fix  = (data.get("fix_description") or "")[:90]
                    print(f"    \U0001f9e0 AI diag : {diag}")
                    print(f"    \U0001f9e0 AI fix  : {fix}")

                elif event == "pest_result":
                    st   = data.get("status", "?")
                    icon = PASS if st == "pass" else FAIL
                    print(f"    \U0001f9ea Pest {icon} {st.upper()} ({data.get('duration_ms')}ms)")
                    if st == "pass":
                        summary["pest_pass"] = True
                    elif st == "fail":
                        snippet = str(data.get("output", ""))[:250]
                        print(f"         \u21b3 {snippet}")

                elif event == "mutation_result":
                    score  = data.get("score")
                    passed = data.get("passed")
                    icon   = PASS if passed else FAIL
                    print(f"    \U0001f9ec Mutation {icon} {score}% (need {data.get('threshold')}%)")
                    summary["mutation_score"] = score

                elif event == "patch_applied":
                    print(f"    \u2699\ufe0f  Patch: {data.get('action')} — {str(data.get('fix',''))[:70]}")

                elif event == "complete":
                    summary["status"]     = data.get("status", "unknown")
                    summary["iterations"] = data.get("iterations", 0)
                    if data.get("mutation_score") is not None:
                        summary["mutation_score"] = data.get("mutation_score")
                    icon = PASS if summary["status"] == "success" else FAIL
                    print(f"\n    {icon} COMPLETE — {summary['status'].upper()}")
                    break  # stop reading stream

                elif event == "error":
                    msg = data.get("msg") or data.get("message", "")
                    summary["errors"].append(msg)
                    print(f"    \U0001f6a8 ERROR: {msg[:120]}")

    summary["duration_s"] = round(time.monotonic() - start, 1)
    return summary


async def run_case(case: str) -> dict:
    print(f"\n{'='*65}")
    print(f"  CASE: {case.upper()}")
    print(f"{'='*65}")
    code = load_code(case)

    async with httpx.AsyncClient(timeout=30) as client:
        try:
            jwt_token = await get_session_token(client)
            sub_id = await submit_repair(client, case, code, jwt_token)
        except Exception as exc:
            print(f"  \U0001f6a8 Submit failed: {exc}")
            return {"case": case, "status": "crashed", "errors": [str(exc)]}

    print(f"  Submission ID: {sub_id}\n")

    try:
        result = await stream_events(sub_id, case, jwt_token)
    except Exception as exc:
        import traceback
        traceback.print_exc()
        print(f"  \U0001f6a8 Stream failed: {exc}")
        return {"case": case, "status": "stream_error", "errors": [str(exc)]}

    icon = PASS if result["status"] == "success" else FAIL
    print(f"\n  {icon} {case.upper()} → status={result['status']} "
          f"| iters={result['iterations']} "
          f"| mutation={result['mutation_score']}% "
          f"| time={result.get('duration_s')}s")
    return result


async def main():
    target = sys.argv[1] if len(sys.argv) > 1 else "all"
    cases  = CASES if target == "all" else [target]

    print(f"\n\U0001f680 LaraVibe Live Test Runner")
    print(f"   Server : {BASE_URL}")
    print(f"   Cases  : {cases}")
    print(f"   Token  : {TOKEN[:18]}...\n")

    results = []
    for case in cases:
        result = await run_case(case)
        results.append(result)

    # ── Summary table ─────────────────────────────────────────────────────────
    print(f"\n\n{'='*65}")
    print(f"  FINAL RESULTS SUMMARY")
    print(f"{'='*65}")
    print(f"  {'Case':<12} {'Status':<12} {'Iters':<7} {'Mutation':<12} {'Time'}")
    print(f"  {'-'*58}")
    passed = 0
    for r in results:
        icon = PASS if r.get("status") == "success" else FAIL
        mut  = f"{r.get('mutation_score')}%" if r.get("mutation_score") is not None else "N/A"
        t    = f"{r.get('duration_s', '?')}s"
        print(f"  {icon} {r.get('case','?'):<10} {r.get('status','?'):<12} "
              f"{r.get('iterations', 0):<7} {mut:<12} {t}")
        if r.get("errors"):
            for e in r["errors"][:2]:
                print(f"      \u21b3 {e[:80]}")
        if r.get("status") == "success":
            passed += 1

    total = len(results)
    overall = PASS if passed == total else FAIL
    print(f"\n  {overall}  Passed: {passed}/{total}")
    print(f"{'='*65}\n")

    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    asyncio.run(main())
