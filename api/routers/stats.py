"""
api/routers/stats.py — Specialized endpoints for research analytics and efficiency trends.
"""
import csv
import io
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc, case
from sqlalchemy.orm import selectinload

from api.database import get_db
from api.models import Submission, Iteration
from api.services.auth_service import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("/summary")
async def get_stats_summary(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Returns high-level research metrics grouped by category.
    Includes success rates and average iterations per error type.
    """
    try:
        status_counts = await db.execute(
            select(Submission.status, func.count(Submission.id))
            .group_by(Submission.status)
        )
        status_map = {row[0]: row[1] for row in status_counts.all()}

        category_metrics = await db.execute(
            select(
                Submission.category,
                func.count(Submission.id).label("count"),
                func.avg(case((Submission.status == 'success', 1.0), else_=0.0)).label("success_rate"),
                func.avg(Submission.total_iterations).label("avg_iterations")
            )
            .where(Submission.category.isnot(None))
            .group_by(Submission.category)
        )

        categories = [
            {
                "name": row[0], "count": row[1],
                "success_rate": round((row[2] or 0.0) * 100, 1),
                "avg_iterations": round(row[3] or 0.0, 2),
            }
            for row in category_metrics.all()
        ]
        return {"overall": status_map, "categories": categories, "total": sum(status_map.values())}
    except Exception as exc:
        logger.error(f"[Stats] summary query failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve stats summary.")


async def _query_summary(db: AsyncSession) -> dict:
    """Internal helper — shared query used by both /summary and / endpoints."""
    return await get_stats_summary.__wrapped__(db)  # type: ignore[attr-defined]


@router.get("/efficiency")
async def get_efficiency_trends(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Returns time-period based efficiency gains.
    Groups submissions by date to show if the system is getting faster/better.
    """
    # Group by date part of created_at
    # In SQLite, we use strftime
    date_field = func.strftime('%Y-%m-%d', Submission.created_at)
    
    trends = await db.execute(
        select(
            date_field.label("date"),
            func.count(Submission.id).label("count"),
            func.avg(Submission.total_iterations).label("avg_iterations"),
            func.avg(case((Submission.status == 'success', 1.0), else_=0.0)).label("success_rate")
        )
        .group_by(date_field)
        .order_by(date_field)
    )

    history = []
    for row in trends.all():
        history.append({
            "date": row[0],
            "count": row[1],
            "avg_iterations": round(row[2], 2),
            "success_rate": round(row[3] * 100, 1)
        })

    return {"trends": history}


@router.get("/export")
async def export_research_data(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    limit: int = Query(1000, ge=1, le=10000, description="Max records to export"),
    offset: int = Query(0, ge=0, description="Number of records to skip"),
):
    """
    Exports paginated research CSV. Use limit/offset for large datasets.
    """
    result = await db.execute(
        select(Submission)
        .options(selectinload(Submission.iterations))
        .order_by(desc(Submission.created_at))
        .offset(offset)
        .limit(limit)
    )
    submissions = result.scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    
    writer.writerow([
        "submission_id", "created_at", "status", "category", "case_id", 
        "experiment_id", "total_iterations", "best_mutation_score"
    ])

    for sub in submissions:
        best_mut = 0.0
        if sub.iterations:
            scores = [i.mutation_score for i in sub.iterations if i.mutation_score is not None]
            best_mut = max(scores) if scores else 0.0

        writer.writerow([
            sub.id,
            sub.created_at.isoformat(),
            sub.status,
            sub.category or "manual",
            sub.case_id or "N/A",
            sub.experiment_id or "legacy",
            sub.total_iterations,
            best_mut
        ])

    response = Response(content=output.getvalue(), media_type="text/csv")
    response.headers["Content-Disposition"] = f"attachment; filename=repair_research_{datetime.now().strftime('%Y%m%d')}.csv"
    return response


@router.get("/")
async def get_unified_stats(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Unified endpoint for the frontend dashboard. Safe on empty DB."""
    try:
        status_counts = await db.execute(
            select(Submission.status, func.count(Submission.id))
            .group_by(Submission.status)
        )
        status_map = {row[0]: row[1] for row in status_counts.all()}

        category_metrics = await db.execute(
            select(
                Submission.category,
                func.count(Submission.id).label("count"),
                func.avg(case((Submission.status == 'success', 1.0), else_=0.0)).label("success_rate"),
                func.avg(Submission.total_iterations).label("avg_iterations")
            )
            .where(Submission.category.isnot(None))
            .group_by(Submission.category)
        )
        categories = [
            {
                "name": row[0], "count": row[1],
                "success_rate": round((row[2] or 0.0) * 100, 1),
                "avg_iterations": round(row[3] or 0.0, 2),
            }
            for row in category_metrics.all()
        ]

        avg_metrics = await db.execute(
            select(
                func.avg(Submission.total_iterations),
                func.avg(Iteration.mutation_score)
            )
            .join(Iteration, Submission.id == Iteration.submission_id)
            .where(Submission.status == 'success')
        )
        # .first() returns None when there are no successful submissions yet
        avg_row = avg_metrics.first()
        avg_iterations    = float(avg_row[0] or 0.0) if avg_row and avg_row[0] is not None else 0.0
        avg_mutation_score = float(avg_row[1] or 0.0) if avg_row and avg_row[1] is not None else 0.0

        total = sum(status_map.values())
        success_count = status_map.get("success", 0)
        global_success_rate = (success_count / total * 100) if total > 0 else 0.0

        return {
            "global_success_rate": round(global_success_rate, 1),
            "avg_iterations": round(avg_iterations, 2),
            "avg_mutation_score": round(avg_mutation_score, 1),
            "total_repairs": total,
            "categories": categories,
            "status_distribution": status_map,
        }
    except Exception as exc:
        logger.error(f"[Stats] unified stats query failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve unified stats.")
