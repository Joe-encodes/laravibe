import asyncio
import os
import pathlib
import sys

# Add project root to path
sys.path.append(str(pathlib.Path(__file__).parent.parent))

from sqlalchemy import select, update
from sqlalchemy.orm import selectinload
from api.database import get_sessionmaker
from api.models import Submission, Iteration, RepairSummary

async def clean_database():
    print("Starting database cleanup...")
    session_factory = get_sessionmaker()
    async with session_factory() as session:
        # 1. Clean Submissions
        print("Cleaning Submissions...")
        result = await session.execute(
            select(Submission).options(selectinload(Submission.iterations))
        )
        submissions = result.scalars().all()
        for sub in submissions:
            if not sub.total_iterations:
                sub.total_iterations = len(sub.iterations)
            if sub.user_prompt is None:
                sub.user_prompt = "No prompt provided"
            if sub.category is None:
                sub.category = "SYSTEM_REPAIR"

        # 2. Clean Iterations
        print("Cleaning Iterations...")
        result = await session.execute(select(Iteration))
        iterations = result.scalars().all()
        for it in iterations:
            if it.ai_prompt is None:
                it.ai_prompt = "[Retroactively inferred. Not recorded during execution.]"
            if it.planner_model is None:
                it.planner_model = "unknown"
            if it.executor_model is None:
                it.executor_model = "unknown"
            if it.reviewer_model is None:
                it.reviewer_model = "unknown"
            if it.failure_reason is None and it.status == "failed":
                it.failure_reason = "unknown"
            if it.pest_test_result is None:
                it.pest_test_result = "No test output recorded."

        # 3. Clean RepairSummaries
        print("Cleaning RepairSummaries...")
        result = await session.execute(select(RepairSummary))
        summaries = result.scalars().all()
        for summary in summaries:
            if summary.what_did_not_work is None:
                summary.what_did_not_work = "N/A"

        print("Committing changes...")
        await session.commit()
        print("Cleanup complete!")

if __name__ == "__main__":
    asyncio.run(clean_database())
