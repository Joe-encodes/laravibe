
"""
api/routers/history.py — GET /api/history endpoint.
Returns last 20 submissions for the history panel.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from sqlalchemy.orm import selectinload

from api.database import get_db
from api.models import Submission
from api.schemas import HistoryItem, SubmissionOut
from api.services.auth_service import get_current_user

router = APIRouter(prefix="/api", tags=["history"])


@router.get("/history", response_model=list[HistoryItem])
async def get_history(
    skip: int = 0,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    """Return the last `limit` submissions, newest first, offset by `skip`."""
    result = await db.execute(
        select(Submission)
        .order_by(desc(Submission.created_at))
        .offset(skip)
        .limit(limit)
    )
    return result.scalars().all()


@router.get("/history/{submission_id}", response_model=SubmissionOut)
async def get_history_detail(
    submission_id: str,
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    """Return full details for a single submission by ID."""
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
