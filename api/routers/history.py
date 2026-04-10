"""
api/routers/history.py — GET /api/history endpoint.
Returns last 20 submissions for the history panel.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from api.database import get_db
from api.models import Submission
from api.schemas import HistoryItem, SubmissionOut

router = APIRouter(prefix="/api", tags=["history"])


@router.get("/history", response_model=list[HistoryItem])
async def get_history(
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
):
    """Return the last `limit` submissions (default 20), newest first."""
    result = await db.execute(
        select(Submission)
        .order_by(desc(Submission.created_at))
        .limit(limit)
    )
    return result.scalars().all()


@router.get("/history/{submission_id}", response_model=SubmissionOut)
async def get_history_detail(
    submission_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Return full details for a single submission by ID."""
    from fastapi import HTTPException
    
    # We load the submission, but since iterations/tests are lazy-loaded by default,
    # we need to join load them or rely on schema loading.
    # We will use selectinload to eagerly load the relationships.
    from sqlalchemy.orm import selectinload
    
    result = await db.execute(
        select(Submission)
        .options(
            selectinload(Submission.iterations)
        )
        .where(Submission.id == submission_id)
    )
    submission = result.scalar_one_or_none()
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")
        
    return submission
