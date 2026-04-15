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

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from api.config import get_settings
from api.database import get_db
from api.models import Submission
from api.schemas import RepairRequest, RepairSubmitResponse, SubmissionOut
from api.services import repair_service

router = APIRouter(prefix="/api", tags=["repair"])
settings = get_settings()

# In-memory event queues per submission_id (for SSE)
# In production, replace with Redis pub/sub or database
_event_queues: dict[str, list[dict]] = {}
_repair_done: dict[str, bool] = {}


@router.post("/repair", response_model=RepairSubmitResponse, status_code=202)
async def submit_repair(
    request: RepairRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Submit PHP code for repair. Returns submission_id immediately."""
    # Validate code size
    if len(request.code.encode("utf-8")) > settings.max_code_size_kb * 1024:
        raise HTTPException(400, f"Code exceeds maximum size of {settings.max_code_size_kb}KB")

    # Create submission record
    submission_id = str(uuid.uuid4())
    submission = Submission(
        id=submission_id,
        created_at=datetime.now(timezone.utc),
        original_code=request.code,
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
        code=request.code,
        max_iterations=request.max_iterations,
        use_boost=request.use_boost,
        use_mutation_gate=request.use_mutation_gate,
    )

    return RepairSubmitResponse(submission_id=submission_id)


async def _run_repair_background(
    submission_id: str,
    code: str,
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
            db=db,
            max_iterations=max_iterations,
            use_boost=use_boost,
            use_mutation_gate=use_mutation_gate,
        ):
            _event_queues.setdefault(submission_id, []).append(event)
    _repair_done[submission_id] = True


@router.get("/repair/{submission_id}/stream")
async def stream_repair(submission_id: str, db: AsyncSession = Depends(get_db)):
    """
    SSE endpoint — streams live repair events.
    Connect with: new EventSource('/api/repair/<id>/stream')
    """
    submission = await db.get(Submission, submission_id)
    if not submission:
        raise HTTPException(404, f"Submission {submission_id} not found")

    async def event_generator() -> AsyncGenerator[str, None]:
        import asyncio
        sent_idx = 0
        while True:
            queue = _event_queues.get(submission_id, [])
            while sent_idx < len(queue):
                evt = queue[sent_idx]
                yield f"data: {json.dumps(evt)}\n\n"
                sent_idx += 1

            if _repair_done.get(submission_id, False) and sent_idx >= len(queue):
                break
            await asyncio.sleep(0.2)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/repair/{submission_id}", response_model=SubmissionOut)
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
