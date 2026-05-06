"""
api/routers/admin.py — Authenticated admin-only endpoints.

GET /api/admin/training-dataset  — anonymized successful repairs for research
GET /api/admin/evaluations       — aggregated batch evaluation history
"""
import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, case, desc

from api.database import get_db
from api.models import Submission
from api.services.auth_service import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/training-dataset")
async def get_training_dataset(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Returns anonymized successful repair events for training data.
    Strips user_id and other PII. Requires authentication.
    """
    try:
        stmt = (
            select(Submission)
            .where(Submission.status == "success")
            .order_by(Submission.created_at.desc())
            .limit(100)
        )
        result = await db.execute(stmt)
        submissions = result.scalars().all()

        return {
            "total": len(submissions),
            "data": [
                {
                    "id": sub.id,
                    "original_code": sub.original_code,
                    "final_code": sub.final_code,
                    "total_iterations": sub.total_iterations,
                    "error_summary": sub.error_summary,
                    "category": sub.category,
                    "created_at": sub.created_at,
                }
                for sub in submissions
            ],
        }
    except Exception as exc:
        logger.error(f"[Admin] training-dataset query failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve training dataset.")


@router.get("/evaluations")
async def get_evaluations(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Returns aggregated batch evaluation history grouped by experiment_id.
    Reads real data from the submissions table — no placeholders.
    """
    try:
        stmt = (
            select(
                Submission.experiment_id,
                func.count(Submission.id).label("total_cases"),
                func.sum(case((Submission.status == "success", 1), else_=0)).label("success_count"),
                func.min(Submission.created_at).label("created_at"),
            )
            .where(Submission.experiment_id.isnot(None))
            .group_by(Submission.experiment_id)
            .order_by(desc("created_at"))
        )

        result = await db.execute(stmt)
        rows = result.all()

        output = []
        for row in rows:
            total = row.total_cases or 0
            success = row.success_count or 0  # guard against NULL from SUM on empty set
            rate = round(success / total * 100, 1) if total > 0 else 0.0
            output.append({
                "id": row.experiment_id,
                "total_cases": total,
                "success_count": success,
                "success_rate_pct": rate,
                "created_at": row.created_at,
            })

        return output

    except Exception as exc:
        logger.error(f"[Admin] evaluations query failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve evaluations.")
