"""
api/routers/repair.py — Core repair endpoints + SSE stream.

POST /api/repair              Submit code → 202 with submission_id
GET  /api/repair/{id}         Get full result + iterations
GET  /api/repair/{id}/stream  SSE stream of live repair progress
"""
import json
import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from api.config import get_settings
from api.database import get_db
from api.models import Submission
from api.schemas import RepairRequest, RepairSubmitResponse, SubmissionOut
from api.services.repair import run_repair_loop
from api.services.auth_service import get_current_user
from api.limiter import limiter

router = APIRouter(prefix="/api", tags=["repair"])
settings = get_settings()

# In-memory event queues per submission_id (for SSE)
# In production, replace with Redis pub/sub or database
_event_queues: dict[str, list[dict]] = {}
_repair_done: dict[str, bool] = {}


@router.post("/repair", response_model=RepairSubmitResponse, status_code=202)
@limiter.limit("10/minute")
async def submit_repair(
    request: Request,
    repair_request: RepairRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    """Submit PHP code for repair. Returns submission_id immediately. Rate-limited to 10/minute."""
    # Validate code size
    if len(repair_request.code.encode("utf-8")) > settings.max_code_size_kb * 1024:
        raise HTTPException(400, f"Code exceeds maximum size of {settings.max_code_size_kb}KB")

    # Create submission record
    submission_id = str(uuid.uuid4())
    submission = Submission(
        id=submission_id,
        created_at=datetime.now(timezone.utc),
        original_code=repair_request.code,
        status="pending",
    )
    db.add(submission)
    await db.commit()

    # Set up event queue for SSE
    _event_queues[submission_id] = []
    _repair_done[submission_id] = False

    # Run repair loop as background task
    background_tasks.add_task(
        _run_repair_background,
        submission_id=submission_id,
        code=repair_request.code,
        prompt=repair_request.prompt,
        max_iterations=repair_request.max_iterations,
        use_boost=repair_request.use_boost,
        use_mutation_gate=repair_request.use_mutation_gate,
    )

    return RepairSubmitResponse(submission_id=submission_id)


async def _run_repair_background(
    submission_id: str,
    code: str,
    prompt: str | None,
    max_iterations: int | None,
    use_boost: bool,
    use_mutation_gate: bool,
) -> None:
    """Background task: runs the repair loop and pushes events to the SSE queue."""
    from api.database import AsyncSessionLocal
    import traceback as _tb
    try:
        async with AsyncSessionLocal() as db:
            async for event in run_repair_loop(
                submission_id=submission_id,
                code=code,
                prompt=prompt,
                db=db,
                max_iterations=max_iterations,
                use_boost=use_boost,
                use_mutation_gate=use_mutation_gate,
            ):
                _event_queues.setdefault(submission_id, []).append(event)
    except Exception as exc:
        # Ensure the submission is never left stuck in "pending".
        err_msg = str(exc)
        logger.error(
            f"[Repair BG] submission {submission_id} crashed: {err_msg}\n{_tb.format_exc()}"
        )
        # Push a terminal error event so the SSE consumer knows it's over.
        _event_queues.setdefault(submission_id, []).append({
            "event": "error",
            "data": {
                "submission_id": submission_id,
                "message": f"Internal repair loop error: {err_msg}",
            },
        })
        # Mark the submission as failed in the DB.
        try:
            async with AsyncSessionLocal() as db:
                from sqlalchemy import update
                from api.models import Submission as _Sub
                await db.execute(
                    update(_Sub)
                    .where(_Sub.id == submission_id)
                    .values(status="failed", error_summary=f"[CRASH] {err_msg[:500]}")
                )
                await db.commit()
        except Exception as db_exc:
            logger.error(f"[Repair BG] Could not mark submission {submission_id} as failed: {db_exc}")
    finally:
        _repair_done[submission_id] = True


@router.get("/repair/{submission_id}/stream")
async def stream_repair(
    submission_id: str, 
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """
    SSE endpoint — streams live repair events.
    Connect with: new EventSource('/api/repair/<id>/stream?token=<token>')
    """
    submission = await db.get(Submission, submission_id)
    if not submission:
        raise HTTPException(404, f"Submission {submission_id} not found")

    async def event_generator() -> AsyncGenerator[str, None]:
        import asyncio
        from sqlalchemy.orm import selectinload
        
        # 1. If submission is already finished, playback from DB
        if submission.status in ["success", "failed"]:
            # Reload with iterations
            stmt = select(Submission).where(Submission.id == submission_id).options(selectinload(Submission.iterations))
            res = await db.execute(stmt)
            sub_with_its = res.scalar_one()
            
            for iteration in sorted(sub_with_its.iterations, key=lambda x: x.iteration_num):
                if iteration.pipeline_logs:
                    try:
                        logs = json.loads(iteration.pipeline_logs)
                        for evt in logs:
                            evt_type = evt.get("event", "info")
                            evt_data = evt.get("data", {})
                            yield f"event: {evt_type}\ndata: {json.dumps({'event': evt_type, 'data': evt_data})}\n\n"
                            await asyncio.sleep(0.01) # Small delay for smooth playback
                    except Exception:
                        continue
            yield f"event: complete\ndata: {json.dumps({'event': 'complete', 'data': {'status': submission.status}})}\n\n"
            return

        # 2. Live stream for ongoing repairs
        sent_idx = 0
        try:
            while True:
                queue = _event_queues.get(submission_id, [])
                while sent_idx < len(queue):
                    evt = queue[sent_idx]
                    evt_type = evt.get("event", "info")
                    evt_data = evt.get("data", {})
                    yield f"event: {evt_type}\ndata: {json.dumps({'event': evt_type, 'data': evt_data})}\n\n"
                    sent_idx += 1

                if _repair_done.get(submission_id, False) and sent_idx >= len(queue):
                    break
                
                # Check if submission finished while we were waiting
                await db.refresh(submission)
                if submission.status in ["success", "failed"]:
                    # Wait a bit for the last events to hit the queue
                    await asyncio.sleep(1)
                    if sent_idx >= len(_event_queues.get(submission_id, [])):
                        break

                await asyncio.sleep(0.2)
        finally:
            # Only cleanup if we were the ones running the live stream
            if submission.status not in ["success", "failed"]:
                _event_queues.pop(submission_id, None)
                _repair_done.pop(submission_id, None)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/repair/{submission_id}", response_model=SubmissionOut)
async def get_repair_status(
    submission_id: str, 
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    """Get the current status and all iteration details for a submission."""
    result = await db.execute(
        select(Submission)
        .where(Submission.id == submission_id)
        .options(selectinload(Submission.iterations))
    )
    submission = result.scalar_one_or_none()
    if not submission:
        raise HTTPException(404, f"Submission {submission_id} not found")
    return submission


@router.delete("/repair/{submission_id}", status_code=200)
async def cancel_repair(
    submission_id: str,
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    """Signal an ongoing repair to stop at the next iteration."""
    submission = await db.get(Submission, submission_id)
    if not submission:
        raise HTTPException(404, f"Submission {submission_id} not found")
    
    if submission.status not in ["pending", "running"]:
        raise HTTPException(400, f"Cannot cancel submission in '{submission.status}' state.")

    submission.is_cancelled = True
    submission.status = "failed"
    submission.error_summary = "Cancelled by user"
    
    # KILL SWITCH: Immediate container destruction
    if submission.container_id:
        try:
            from api.services.sandbox import manager as sandbox
            await sandbox.destroy_sandbox(submission.container_id)
            logger.info(f"[Repair] Force killed container {submission.container_id} for submission {submission_id}")
        except Exception as e:
            logger.warning(f"[Repair] Failed to kill container {submission.container_id}: {e}")

    await db.commit()
    
    return {"message": f"Kill signal sent for {submission_id}. Sandbox destroyed."}
