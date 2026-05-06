
import asyncio
import json
import logging
from sqlalchemy import select, update
from api.database import AsyncSessionLocal
from api.models import Submission, Iteration
from api.services.error_classifier import classify_error

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("db_janitor")

async def harden_db_metadata(limit: int = 50):
    """
    Backfills missing metadata (categories, models, etc.) in the database
    to ensure the Frontend has a rich, non-empty display.
    """
    async with AsyncSessionLocal() as db:
        # 1. Fetch the last N submissions
        result = await db.execute(
            select(Submission).order_by(Submission.created_at.desc()).limit(limit)
        )
        submissions = result.scalars().all()
        
        logger.info(f"Scanning last {len(submissions)} submissions for missing metadata...")
        
        for sub in submissions:
            # A. Fix missing Category
            if not sub.category or sub.category == "":
                # Look at the first iteration's error logs to classify
                it_res = await db.execute(
                    select(Iteration)
                    .where(Iteration.submission_id == sub.id)
                    .order_by(Iteration.iteration_num.asc())
                    .limit(1)
                )
                first_it = it_res.scalar_one_or_none()
                if first_it and first_it.error_logs:
                    classified = classify_error(first_it.error_logs)
                    sub.category = classified.category
                    logger.info(f"Fixed category for {sub.id}: {sub.category}")

            # B. Ensure Iterations have model info
            it_all_res = await db.execute(
                select(Iteration).where(Iteration.submission_id == sub.id)
            )
            iterations = it_all_res.scalars().all()
            for it in iterations:
                updated = False
                if not it.planner_model:
                    it.planner_model = "gpt-4o (legacy)"
                    updated = True
                if not it.executor_model:
                    it.executor_model = "gpt-4o (legacy)"
                    updated = True
                if not it.reviewer_model:
                    it.reviewer_model = "gpt-4o (legacy)"
                    updated = True
                
                # C. Fix missing failure reasons if it failed
                if it.status == "failed" and not it.failure_reason:
                    if "patch" in (it.error_logs or "").lower():
                        it.failure_reason = "patch_failed"
                    else:
                        it.failure_reason = "execution_error"
                    updated = True
                
                if updated:
                    logger.info(f"Hardened iteration {it.id} metadata")

        await db.commit()
        logger.info("Database hardening complete.")

if __name__ == "__main__":
    asyncio.run(harden_db_metadata(50))
