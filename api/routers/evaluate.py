"""
api/routers/evaluate.py — GET /api/evaluate (Grok addition).
Runs all PHP files in /samples/ through the repair loop and returns a success rate report.
Great for thesis demos and ablation experiments.
"""
import pathlib
import time
from fastapi import APIRouter, Depends, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_db, AsyncSessionLocal
from api.schemas import EvaluateResponse, EvaluateCaseResult

router = APIRouter(prefix="/api", tags=["evaluate"])

SAMPLES_DIR = pathlib.Path("samples")


@router.get("/evaluate", response_model=EvaluateResponse)
async def evaluate_samples(db: AsyncSession = Depends(get_db)):
    """
    Run every PHP file in the /samples/ directory through the repair loop.
    Returns per-case results + overall success rate.
    Useful for thesis demo and comparing Boost vs no-Boost runs.
    """
    from api.services import repair_service
    import uuid
    from datetime import datetime, timezone
    from api.models import Submission

    sample_files = sorted(SAMPLES_DIR.glob("*.php")) if SAMPLES_DIR.exists() else []

    if not sample_files:
        return EvaluateResponse(
            total_cases=0,
            success_count=0,
            success_rate_pct=0.0,
            cases=[],
        )

    results = []
    for sample_path in sample_files:
        code = sample_path.read_text(encoding="utf-8")
        submission_id = str(uuid.uuid4())
        start = time.monotonic()

        status = "failed"
        iterations_done = 0
        mutation_score = None

        async with AsyncSessionLocal() as session:
            submission = Submission(
                id=submission_id,
                created_at=datetime.now(timezone.utc),
                original_code=code,
                status="pending",
            )
            session.add(submission)
            await session.commit()

            async for evt in repair_service.run_repair_loop(
                submission_id=submission_id,
                code=code,
                db=session,
            ):
                if evt["event"] == "complete":
                    status = evt["data"].get("status", "failed")
                    iterations_done = evt["data"].get("iterations", 0)
                    mutation_score = evt["data"].get("mutation_score")

        results.append(EvaluateCaseResult(
            sample_file=sample_path.name,
            status=status,
            iterations=iterations_done,
            mutation_score=mutation_score,
            duration_s=round(time.monotonic() - start, 2),
        ))

    success_count = sum(1 for r in results if r.status == "success")
    return EvaluateResponse(
        total_cases=len(results),
        success_count=success_count,
        success_rate_pct=round(success_count / len(results) * 100, 1),
        cases=results,
    )
