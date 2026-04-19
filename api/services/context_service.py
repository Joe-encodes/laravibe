"""
api/services/context_service.py — Historical repair summarization and retrieval.

Progressive learning system (Phase 7). When a repair loop hits 100% success,
we summarize what worked and what didn't. On future submissions with a
similar error signature, we inject those past summaries so the LLM skips
the guesswork.
"""
import logging
import re
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models import RepairSummary

logger = logging.getLogger(__name__)

async def store_repair_summary(
    db: AsyncSession, 
    error_text: str, 
    diagnosis: str, 
    fix_applied: str, 
    failed_diagnoses: list[str], 
    iterations_needed: int
) -> None:
    """Save a successful repair into the knowledge base."""
    # Simple extraction of the key error line for indexing
    error_type = _extract_error_signature(error_text)
    
    summary = RepairSummary(
        error_type=error_type,
        diagnosis=diagnosis,
        fix_applied=fix_applied,
        what_did_not_work="; ".join(failed_diagnoses) if failed_diagnoses else None,
        iterations_needed=iterations_needed
    )
    db.add(summary)
    await db.commit()
    logger.info(f"[ContextDB] Saved repair summary for error: {error_type}")

async def retrieve_similar_repairs(db: AsyncSession, error_text: str) -> str:
    """
    Find relevant past repairs for this error and format them as a prompt addendum.
    Uses simple substring matching on the error signature for v1.
    """
    error_type = _extract_error_signature(error_text)
    if not error_type or len(error_type) < 10:
        return ""
        
    stmt = (
        select(RepairSummary)
        .where(RepairSummary.error_type == error_type)
        .order_by(RepairSummary.created_at.desc())
        .limit(3)
    )
    result = await db.execute(stmt)
    summaries = result.scalars().all()
    
    if not summaries:
        return ""
        
    context = "The system found previous successful repairs for exactly this error signature:\n\n"
    
    for i, s in enumerate(summaries, 1):
        context += f"### Past Fix {i} (Solved in {s.iterations_needed} iterations)\n"
        context += f"- **Diagnosis that worked:** {s.diagnosis}\n"
        context += f"- **Fix Applied:** {s.fix_applied}\n"
        if s.what_did_not_work:
            context += f"- **DEAD ENDS to completely avoid:** {s.what_did_not_work}\n"
        context += "\n"
        
    return context.strip()

def _extract_error_signature(error_text: str) -> str:
    """Extract the core error line (e.g. 'Class App\Models\Product not found') to group similar errors."""
    if not error_text:
        return "Unknown error"
        
    # Look for PHP Fatal errors, exceptions, or Pest failure messages
    # We use findall and take the last match [-1] to ensure we get the latest exception
    
    # 0. Laravel app log exception
    laravel_exceptions = re.findall(r"local\.ERROR:\s*(.*?)(?=\s+\{|$)", error_text)
    if laravel_exceptions:
        return laravel_exceptions[-1].strip()

    # 1. PHP Exception message
    exceptions = re.findall(r"Exception:\s*(.*)", error_text)
    if exceptions:
        return exceptions[-1].strip()
    
    # 2. PHP Fatal error line
    fatals = re.findall(r"Fatal error:\s*(.*?)\s*in /", error_text)
    if fatals:
        return fatals[-1].strip()
        
    # 3. Class not found format
    classes = re.findall(r"Class\s+.*?\s+not found", error_text)
    if classes:
        return classes[-1].strip()
        
    # Fallback: Just grab the first non-empty line and truncate it
    lines = [L.strip() for L in error_text.split("\n") if L.strip() and not L.startswith("===")]
    if lines:
        return lines[0][:200]
        
    return "Unknown error"
