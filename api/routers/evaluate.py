"""
api/routers/evaluate.py — POST /api/evaluate + GET /api/evaluate/{experiment_id}

All heavy orchestration (YAML loading, repair loop, CSV writing) lives in
api/services/evaluation_service.py. This router is intentionally thin:
auth → generate ID → hand off → return immediate 202-style response.
"""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_db
from api.schemas import EvaluateBatchResponse
from api.services.auth_service import get_current_user
from api.services import evaluation_service
from api.limiter import limiter

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["evaluate"])


@router.post("/evaluate", response_model=EvaluateBatchResponse)
@limiter.limit("2/minute")
async def evaluate_samples(
    background_tasks: BackgroundTasks,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Start a batch evaluation of all test cases in batch_manifest.yaml.
    Returns immediately with an experiment_id for status tracking.
    Poll GET /api/evaluate/{experiment_id} or check /api/admin/evaluations.
    """
    experiment_id = f"batch-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    logger.info(f"Queuing batch evaluation {experiment_id}")

    background_tasks.add_task(evaluation_service.run_batch_evaluation, experiment_id)

    return EvaluateBatchResponse(
        experiment_id=experiment_id,
        status="running",
        total_cases=0,
        success_count=0,
        success_rate_pct=0.0,
        cases=[],
    )


@router.get("/evaluate/{experiment_id}")
async def get_evaluation_status(
    experiment_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Returns status + aggregated results for a batch experiment.
    Reads directly from DB — not an in-memory dict — so survives server restarts.
    """
    from sqlalchemy import select, func, case as sa_case
    from api.models import Submission

    rows = await db.execute(
        select(
            Submission.status,
            func.count(Submission.id).label("count"),
        )
        .where(Submission.experiment_id == experiment_id)
        .group_by(Submission.status)
    )
    status_map = {row.status: row.count for row in rows}

    if not status_map:
        return {"status": "not_found", "experiment_id": experiment_id}

    total = sum(status_map.values())
    running = status_map.get("running", 0) + status_map.get("pending", 0)
    success_count = status_map.get("success", 0)

    overall = "running" if running > 0 else "completed"
    rate = round(success_count / total * 100, 1) if total > 0 else 0.0

    return {
        "experiment_id": experiment_id,
        "status": overall,
        "total_cases": total,
        "success_count": success_count,
        "success_rate_pct": rate,
        "status_distribution": status_map,
    }
