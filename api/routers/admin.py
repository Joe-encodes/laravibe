from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List

from api.database import get_db
from api.models import Submission

router = APIRouter(prefix="/admin", tags=["admin"])

@router.get("/training-dataset")
async def get_training_dataset(
    db: AsyncSession = Depends(get_db),
    # In a full setup, we would verify a Supabase JWT token here and check if user_id is an admin
    authorization: str = Header(None) 
):
    """
    Returns anonymized successful repair loop events for training data.
    Strips out user_id and other PII.
    """
    # Simple dummy auth check for the scaffold
    if not authorization or "Bearer" not in authorization:
        # For the sake of the scaffold, let's not block it yet, but in prod we would raise 401
        pass 

    stmt = select(Submission).where(Submission.status == "success").order_by(Submission.created_at.desc()).limit(100)
    result = await db.execute(stmt)
    submissions = result.scalars().all()
    
    anonymized_data = []
    for sub in submissions:
        anonymized_data.append({
            "id": sub.id,  # Still sending id to be able to render it uniquely
            "original_code": sub.original_code,
            "final_code": sub.final_code,
            "iterations": sub.total_iterations,
            "error_summary": sub.error_summary,
            "category": sub.category,
            "created_at": sub.created_at
        })
        
    return {"total": len(anonymized_data), "data": anonymized_data}
