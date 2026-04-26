"""
api/routers/repair.py — Core repair endpoints + SSE stream.

POST /api/repair              Submit code → 202 with submission_id
GET  /api/repair/{id}         Get full result + iterations
GET  /api/repair/{id}/stream  SSE stream of live repair progress
"""
import json
import uuid
import time
import asyncio
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
from api.schemas import RepairRequest, RepairAcceptedResponse, SubmissionResponse
from api.services import repair_service
from api.services.auth_service import get_current_user
from api.limiter import limiter

router = APIRouter(prefix="/api", tags=["repair"])
settings = get_settings()

# In-memory event queues per submission_id (for SSE)
# In production, replace with Redis pub/sub or database
_event_queues: dict[str, list[dict]] = {}
_repair_done: dict[str, bool] = {}


@router.post("/repair", response_model=RepairAcceptedResponse, status_code=202)
@limiter.limit("20/minute")
async def submit_repair(
    repair_request: RepairRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Submit PHP code for repair. Returns submission_id immediately."""
    # Validate code size
    if len(repair_request.code.encode("utf-8")) > settings.max_code_size_kb * 1024:
        raise HTTPException(400, f"Code exceeds maximum size of {settings.max_code_size_kb}KB")

    # Create submission record
    submission_id = str(uuid.uuid4())
    submission = Submission(
        id=submission_id,
        created_at=datetime.now(timezone.utc),
        original_code=repair_request.code,
        user_prompt=repair_request.prompt,
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

    return RepairAcceptedResponse(submission_id=submission_id)


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
    async with AsyncSessionLocal() as db:
        async for event in repair_service.run_repair_loop(
            submission_id=submission_id,
            code=code,
            prompt=prompt,
            db=db,
            max_iterations=max_iterations,
            use_boost=use_boost,
            use_mutation_gate=use_mutation_gate,
        ):
            _event_queues.setdefault(submission_id, []).append(event)
    _repair_done[submission_id] = True


@router.get("/repair/{submission_id}/stream")
async def stream_repair(
    submission_id: str, 
    token: str | None = None,
    db: AsyncSession = Depends(get_db)
):
    """
    SSE endpoint — streams live repair events.

    Uses query-param auth (?token=MASTER_REPAIR_TOKEN) instead of Bearer headers
    because the browser's EventSource API cannot set custom headers. This is the
    standard pattern for SSE authentication.

    Connect with: new EventSource('/api/repair/<id>/stream?token=<TOKEN>')
    """
    if not token or token != settings.master_repair_token:
        raise HTTPException(401, "Invalid or missing token")
    submission = await db.get(Submission, submission_id)
    if not submission:
        raise HTTPException(404, f"Submission {submission_id} not found")
    
    # CRITICAL: Commit the transaction immediately to release the SQLite SHARED lock.
    # Otherwise, the lock is held open for the entire duration of the stream,
    # completely blocking the background task from saving iterations to the DB.
    await db.commit()

    async def event_generator() -> AsyncGenerator[str, None]:
        import asyncio
        sent_idx = 0
        last_heartbeat = time.time()
        while True:
            queue = _event_queues.get(submission_id, [])
            while sent_idx < len(queue):
                evt = queue[sent_idx]
                yield f"data: {json.dumps(evt)}\n\n"
                sent_idx += 1
                last_heartbeat = time.time()

            if _repair_done.get(submission_id, False) and sent_idx >= len(queue):
                # Cleanup memory after a grace period
                await asyncio.sleep(30)
                _event_queues.pop(submission_id, None)
                _repair_done.pop(submission_id, None)
                break
            
            # Send heartbeat ping every 15s to keep connection alive
            if time.time() - last_heartbeat > 15:
                yield ": ping\n\n"
                last_heartbeat = time.time()
                
            await asyncio.sleep(0.5)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/repair/{submission_id}", response_model=SubmissionResponse)
async def get_repair_status(submission_id: str, db: AsyncSession = Depends(get_db)):
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
