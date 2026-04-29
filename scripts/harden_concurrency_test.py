import asyncio
import httpx
import time
import json

APP_URL = "http://localhost:8000"
TOKEN = "laravibe-repair-2026-safe-token"

CODE_1 = """<?php
namespace App\\Http\\Controllers;
class Test1 {
    public function index() { return Product::all(); }
}
"""

CODE_2 = """<?php
namespace App\\Http\\Controllers;
class Test2 {
    public function show($id) { return Product::find($id); }
}
"""

async def submit_repair(client, code, name):
    print(f"🚀 [{name}] Submitting repair...")
    resp = await client.post(
        f"{APP_URL}/api/repair",
        headers={"Authorization": f"Bearer {TOKEN}"},
        json={"code": code, "max_iterations": 2}
    )
    data = resp.json()
    submission_id = data["submission_id"]
    print(f"✅ [{name}] Submission ID: {submission_id}")
    return submission_id

async def monitor_repair(client, submission_id, name):
    print(f"👀 [{name}] Monitoring {submission_id}...")
    async with client.stream("GET", f"{APP_URL}/api/repair/{submission_id}/stream") as response:
        async for line in response.aiter_lines():
            if line.startswith("data: "):
                event = json.loads(line[6:])
                if event["type"] == "iteration_complete":
                    print(f"✨ [{name}] Iteration {event['num']} complete (success={event['success']})")
                elif event["type"] == "repair_success":
                    print(f"🎉 [{name}] REPAIR SUCCESS!")
                    return True
                elif event["type"] == "repair_failed":
                    print(f"❌ [{name}] REPAIR FAILED.")
                    return False
                elif event["type"] == "error":
                    print(f"🔥 [{name}] ERROR: {event['message']}")
                    return False

async def main():
    async with httpx.AsyncClient(timeout=300) as client:
        # Start two repairs at once
        tasks = [
            submit_repair(client, CODE_1, "Repair A"),
            submit_repair(client, CODE_2, "Repair B")
        ]
        ids = await asyncio.gather(*tasks)
        
        # Monitor both
        monitor_tasks = [
            monitor_repair(client, ids[0], "Repair A"),
            monitor_repair(client, ids[1], "Repair B")
        ]
        results = await asyncio.gather(*monitor_tasks)
        print(f"\nFinal Results: A={results[0]}, B={results[1]}")

if __name__ == "__main__":
    asyncio.run(main())
