
import asyncio
import uuid
from api.database import AsyncSessionLocal
from api.models import Submission
from api.services.repair.orchestrator import run_repair_loop
from sqlalchemy import select

async def verify_replay(original_id: str):
    """
    Simulates a full repair loop but in REPLAY MODE using an existing submission ID.
    This verifies the sandbox and orchestrator logic without calling the LLM.
    """
    async with AsyncSessionLocal() as db:
        # Get original data
        res = await db.execute(select(Submission).where(Submission.id == original_id))
        original_sub = res.scalar_one_or_none()
        if not original_sub:
            print(f"Error: Original submission {original_id} not found.")
            return

        # Create a new "Shadow" submission for the replay run
        shadow_id = f"replay-{str(uuid.uuid4())[:8]}"
        new_sub = Submission(
            id=shadow_id,
            original_code=original_sub.original_code,
            status="pending"
        )
        db.add(new_sub)
        await db.commit()

        print(f"--- STARTING REPLAY OF {original_id} AS {shadow_id} ---")
        
        async for event in run_repair_loop(
            submission_id=shadow_id,
            code=original_sub.original_code,
            db=db,
            replay_submission_id=original_id, # THE REPLAY TRIGGER
            use_boost=False # Skip boost for replay speed
        ):
            evt_type = event.get("event")
            data = event.get("data", {})
            
            if evt_type == "log_line":
                print(f"[LOG] {data.get('msg')}")
            elif evt_type == "iteration_start":
                print(f"\n[ITERATION {data.get('iteration')}] Started")
            elif evt_type == "patch_applied":
                print(f"[PATCH] Applied to {data.get('path')}")
            elif evt_type == "pest_result":
                print(f"[TEST] Pest: {data.get('status').upper()}")
            elif evt_type == "complete":
                print(f"\n--- REPLAY COMPLETE: {data.get('status').upper()} ---")
            elif evt_type == "error":
                print(f"[ERROR] {data.get('msg')}")

if __name__ == "__main__":
    import sys
    # Use the ID we found earlier
    target_id = sys.argv[1] if len(sys.argv) > 1 else "220a8da8-d7f4-4e58-9021-c0ce18e2cec5"
    asyncio.run(verify_replay(target_id))
