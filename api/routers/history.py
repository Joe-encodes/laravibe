"""
api/routers/history.py — GET /api/history endpoint.
Returns last 20 submissions for the history panel.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from api.database import get_db
from api.models import Submission
from api.schemas import HistoryItem

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
