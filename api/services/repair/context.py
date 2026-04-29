
"""
api/services/repair/context.py — Historical repair knowledge and loop safety.
"""
import logging
import re
from collections import deque
from difflib import SequenceMatcher
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from api.models import RepairSummary

logger = logging.getLogger(__name__)

# In-memory sliding window for fast retrieval
_WINDOW_SIZE: int = 200
_SIMILARITY_THRESHOLD: float = 0.6
_repair_cache: deque[dict] = deque(maxlen=_WINDOW_SIZE)
_cache_loaded: bool = False

def _similarity(text1: str, text2: str) -> float:
    if not text1 or not text2: return 0.0
    return SequenceMatcher(None, text1.lower(), text2.lower(), autojunk=False).ratio()

async def _ensure_cache_loaded(db: AsyncSession) -> None:
    global _cache_loaded
    if _cache_loaded: return
    res = await db.execute(select(RepairSummary).order_by(RepairSummary.created_at.desc()).limit(_WINDOW_SIZE))
    for row in reversed(res.scalars().all()):
        _repair_cache.append({
            "error_type": row.error_type,
            "diagnosis": row.diagnosis,
            "fix_applied": row.fix_applied,
            "iterations_needed": row.iterations_needed,
        })
    _cache_loaded = True

async def get_similar_repairs(db: AsyncSession, error_text: str) -> str:
    """Find most relevant past repairs using fuzzy similarity."""
    await _ensure_cache_loaded(db)
    error_sig = _extract_error_signature(error_text)
    if not error_sig or not _repair_cache: return ""

    matches = []
    for entry in _repair_cache:
        sim = _similarity(error_sig, entry["error_type"])
        if sim >= _SIMILARITY_THRESHOLD:
            matches.append((sim, entry))

    if not matches: return ""
    matches.sort(key=lambda x: x[0], reverse=True)
    
    lines = ["## Similar Past Repairs (Knowledge Base)"]
    for i, (_, s) in enumerate(matches[:3], 1):
        lines.append(f"### Past Fix {i} (Solved in {s['iterations_needed']} iterations)")
        lines.append(f"- **Worked Diagnosis:** {s['diagnosis']}")
        lines.append(f"- **Applied Fix:** {s['fix_applied']}")
    
    return "\n".join(lines)

async def store_repair_success(db: AsyncSession, error_text: str, resp: any, iters: int):
    """Save a successful repair to the knowledge base."""
    error_type = _extract_error_signature(error_text)
    summary = RepairSummary(
        error_type=error_type,
        diagnosis=resp.diagnosis,
        fix_applied=resp.fix_description,
        iterations_needed=iters
    )
    db.add(summary)
    # We don't commit here; the orchestrator commits the submission & iteration too
    _repair_cache.append({
        "error_type": error_type, "diagnosis": resp.diagnosis,
        "fix_applied": resp.fix_description, "iterations_needed": iters
    })

def _extract_error_signature(error_text: str) -> str:
    """Extract a stable key for error similarity."""
    if not error_text: return "Unknown"
    # Logic simplified from context_service.py
    for pattern in [r"local\.ERROR:\s*(.*?)(?=\s+\{|$)", r"Exception:\s*(.*)", r"Class\s+.*?\s+not found"]:
        m = re.findall(pattern, error_text)
        if m: return m[-1].strip()
    return error_text.split("\n")[0][:200]
