"""
api/services/context_service.py — Historical repair summarization and retrieval.
Uses a sliding window in-memory cache to retrieve similar past repairs based on error signatures.
"""
import logging
import re
from collections import deque
from difflib import SequenceMatcher

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models import RepairSummary

logger = logging.getLogger(__name__)

# ── Sliding Window Config ─────────────────────────────────────────────────────
_WINDOW_SIZE: int            = 200   # Max cached repairs in memory
_SIMILARITY_THRESHOLD: float = 0.6   # Minimum similarity to surface a match
_TOP_K: int                  = 3     # Max past fixes injected per prompt

# Deque auto-prunes at maxlen — no manual eviction needed
_repair_cache: deque[dict]   = deque(maxlen=_WINDOW_SIZE)
_cache_loaded: bool           = False


# ── Scoring Helpers ───────────────────────────────────────────────────────────

def _similarity(text1: str, text2: str) -> float:
    """Character-level similarity ratio via SequenceMatcher (0.0 – 1.0)."""
    if not text1 or not text2:
        return 0.0
    return SequenceMatcher(None, text1.lower(), text2.lower(), autojunk=False).ratio()


def _retrieval_score(similarity: float, iterations_needed: int) -> float:
    """Combined score favoring high semantic similarity and fewer iterations needed."""
    efficiency = 1.0 / max(iterations_needed, 1)
    return (similarity * 0.7) + (efficiency * 0.3)


# ── Cache Lifecycle ───────────────────────────────────────────────────────────

async def _ensure_cache_loaded(db: AsyncSession) -> None:
    """
    Populate the in-memory cache from DB on the first call (cold start only).
    Subsequent calls return immediately — O(1) guard.
    """
    global _cache_loaded
    if _cache_loaded:
        return

    stmt = (
        select(RepairSummary)
        .order_by(RepairSummary.created_at.desc())
        .limit(_WINDOW_SIZE)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    await db.commit()  # Release the shared lock immediately!

    # Add oldest first so the deque is chronological (newest at the right)
    for row in reversed(rows):
        _repair_cache.append({
            "error_type":       row.error_type,
            "diagnosis":        row.diagnosis,
            "fix_applied":      row.fix_applied,
            "what_did_not_work": row.what_did_not_work,
            "iterations_needed": row.iterations_needed,
        })

    _cache_loaded = True
    logger.info(f"[ContextDB] Sliding cache loaded: {len(_repair_cache)}/{_WINDOW_SIZE} entries")


# ── Public API ────────────────────────────────────────────────────────────────

async def store_repair_summary(
    db: AsyncSession,
    error_text: str,
    diagnosis: str,
    fix_applied: str,
    failed_diagnoses: list[str],
    iterations_needed: int,
) -> None:
    """Persist a successful repair and add it to the sliding window immediately."""
    error_type = _extract_error_signature(error_text)

    summary = RepairSummary(
        error_type=error_type,
        diagnosis=diagnosis,
        fix_applied=fix_applied,
        what_did_not_work="; ".join(failed_diagnoses) if failed_diagnoses else None,
        iterations_needed=iterations_needed,
    )
    db.add(summary)
    await db.commit()

    # Append to in-process deque — deque handles eviction at maxlen automatically
    _repair_cache.append({
        "error_type":        error_type,
        "diagnosis":         diagnosis,
        "fix_applied":       fix_applied,
        "what_did_not_work": summary.what_did_not_work,
        "iterations_needed": iterations_needed,
    })
    logger.info(
        f"[ContextDB] Stored repair for: {error_type!r} | "
        f"Cache size: {len(_repair_cache)}/{_WINDOW_SIZE}"
    )


async def retrieve_similar_repairs(db: AsyncSession, error_text: str) -> str:
    """
    Find the most relevant past repairs using fuzzy similarity + efficiency scoring.

    Algorithm:
      1. Ensure the 200-item sliding window is populated (cold-start DB load).
      2. Score every cached entry in-process — O(200), negligible cost.
      3. Filter entries below _SIMILARITY_THRESHOLD.
      4. Rank by _retrieval_score (similarity * 0.7 + efficiency * 0.3).
      5. Return the top _TOP_K as a formatted prompt addendum.
    """
    await _ensure_cache_loaded(db)

    error_type = _extract_error_signature(error_text)
    if not error_type or len(error_type) < 10:
        return ""

    if not _repair_cache:
        return ""

    scored: list[tuple[float, dict]] = []
    for entry in _repair_cache:
        sim = _similarity(error_type, entry["error_type"])
        if sim >= _SIMILARITY_THRESHOLD:
            scored.append((_retrieval_score(sim, entry["iterations_needed"]), entry))

    if not scored:
        return ""

    scored.sort(key=lambda x: x[0], reverse=True)
    top_matches = scored[:_TOP_K]

    lines = ["The system found similar past repairs ranked by relevance:\n"]
    for i, (score, s) in enumerate(top_matches, 1):
        lines.append(
            f"### Past Fix {i} "
            f"(Relevance: {score:.0%} | Solved in {s['iterations_needed']} iterations)"
        )
        lines.append(f"- **Diagnosis that worked:** {s['diagnosis']}")
        lines.append(f"- **Fix Applied:** {s['fix_applied']}")
        if s.get("what_did_not_work"):
            lines.append(f"- **DEAD ENDS to completely avoid:** {s['what_did_not_work']}")
        lines.append("")

    return "\n".join(lines).strip()


# ── Error Signature Extraction ────────────────────────────────────────────────

def _extract_error_signature(error_text: str) -> str:
    """Extract the most specific error line to use as the similarity key."""
    if not error_text:
        return "Unknown error"

    # 0. Laravel app log exception — most specific
    laravel_exceptions = re.findall(r"local\.ERROR:\s*(.*?)(?=\s+\{|$)", error_text)
    if laravel_exceptions:
        return laravel_exceptions[-1].strip()

    # 1. PHP Exception message
    exceptions = re.findall(r"Exception:\s*(.*)", error_text)
    if exceptions:
        return exceptions[-1].strip()

    # 2. PHP Fatal error
    fatals = re.findall(r"Fatal error:\s*(.*?)\s*in /", error_text)
    if fatals:
        return fatals[-1].strip()

    # 3. Class not found — very common and distinct
    classes = re.findall(r"Class\s+.*?\s+not found", error_text)
    if classes:
        return classes[-1].strip()

    # Fallback: first non-empty non-separator line
    lines = [
        L.strip() for L in error_text.split("\n")
        if L.strip() and not L.startswith("===")
    ]
    if lines:
        return lines[0][:200]

    return "Unknown error"
