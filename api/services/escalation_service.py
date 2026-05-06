
"""
api/services/escalation_service.py — Stuck loop detection and escalation.

Handles Phase 6: detects when the LLM is stuck in a loop of identical
diagnoses or failing patches, and injects stern instructions.

Escalation triggers:
  1. Repeated identical diagnoses (fuzzy match, threshold=3)
  2. Back-to-back patch application failures
  3. create_file was used but the original file still fails
  4. Dependency Guard: AI tries to create_file for a path it already created
"""

import re

# Minimum consecutive identical diagnoses before escalation
STUCK_DIAGNOSIS_THRESHOLD = 3


def _get_words(text: str) -> set:
    return set(re.findall(r'\b\w+\b', text.lower()))


def is_fuzzy_match(text1: str, text2: str, threshold: float = 0.85) -> bool:
    if not text1 or not text2:
        return text1 == text2
    w1 = _get_words(text1)
    w2 = _get_words(text2)
    if not w1 or not w2:
        return text1.strip().lower() == text2.strip().lower()
    
    if len(w1) < 2 or len(w2) < 2:
        return text1.strip().lower() == text2.strip().lower()

    overlap = len(w1.intersection(w2))
    return (overlap / len(w1) >= threshold) or (overlap / len(w2) >= threshold)


def should_force_full_replace(previous_attempts: list[dict]) -> bool:
    """If the LLM has tried to patch twice and failed both times, force full_replace."""
    # We look at the last 2 attempts
    if len(previous_attempts) < 2:
        return False

    last_two = previous_attempts[-2:]
    # Check for 'patch_failed' in failure_reason (mapping to orchestrator outcome)
    return all(a.get("failure_reason") == "patch_failed" for a in last_two)


def _last_action_included_create_file(previous_attempts: list[dict]) -> bool:
    """
    Check if the most recent attempt included creating a new file.
    In orchestrator, this is tracked in the 'files' list.
    """
    if not previous_attempts:
        return False
    # If files were created, they are listed in 'files'
    # We assume 'files' contains paths of NEWLY created dependencies
    return len(previous_attempts[-1].get("files", [])) > 0


def _get_all_created_files(previous_attempts: list[dict]) -> list[str]:
    """
    Return all file paths the AI successfully created in previous attempts.
    """
    seen: set[str] = set()
    for attempt in previous_attempts:
        for path in attempt.get("files", []):
            seen.add(path)
    return list(seen)


def build_escalation_context(previous_attempts: list[dict]) -> str:
    """Build a stern prompt piece when the LLM is stuck."""
    if not previous_attempts:
        return ""

    # Only look at the last 4 attempts to keep context fresh
    recent_attempts = previous_attempts[-4:]
    context = ""

    # 0. Latest Failure Summary (awareness)
    last_attempt = recent_attempts[-1]
    last_reason = last_attempt.get("failure_reason", "unknown")
    last_details = last_attempt.get("failure_details", "No details provided")
    
    context += (
        f"--- LATEST FAILURE SUMMARY (Attempt {last_attempt.get('iteration', '?')}) ---\n"
        f"Result: {last_reason}\n"
        f"Details: {last_details}\n\n"
    )

    # 1. Stuck diagnoses or failure reasons (fuzzy match)
    if len(recent_attempts) >= STUCK_DIAGNOSIS_THRESHOLD:
        # Use a combination of diagnosis and failure_reason for more robust detection
        recent_signals = []
        for a in recent_attempts:
            diag = a.get("diagnosis") or ""
            reason = a.get("failure_reason") or ""
            recent_signals.append(f"{reason} {diag}".strip())

        if len(recent_signals) >= STUCK_DIAGNOSIS_THRESHOLD:
            # Check if the latest is a fuzzy match with the previous ones
            target = recent_signals[-1]
            compare_window = recent_signals[-STUCK_DIAGNOSIS_THRESHOLD:-1]
            
            if all(is_fuzzy_match(target, d) for d in compare_window):
                context += (
                    f"CRITICAL: Your last {STUCK_DIAGNOSIS_THRESHOLD} attempts resulted in essentially the SAME FAILURE.\n"
                    f"System report: '{target[:200]}...'.\n"
                    "This approach is NOT WORKING. You MUST try a completely different logical approach. "
                    "Stop repeating the same reasoning or the same incorrect fixes. "
                    "Look closer at the error trace and the actual file content to find the root cause.\n\n"
                )

    # 2. Patch failures
    if should_force_full_replace(recent_attempts):
        context += (
            "CRITICAL: Your recent patches failed to apply because the 'target' text was not found.\n"
            "DO NOT use action='replace' anymore for this file. You MUST use action='full_replace' "
            "and output the entire complete corrected file. Ensure your TargetContent is EXACT.\n\n"
        )

    # 3. create_file without fixing the original file
    if _last_action_included_create_file(recent_attempts):
        context += (
            "IMPORTANT: In the previous iteration you created a dependency file (e.g. a Model or Migration).\n"
            "The dependency file now EXISTS in the sandbox. Your ONLY job now is to output a `full_replace` "
            "patch for the original submitted file. Do NOT create the dependency again.\n"
            "Include BOTH the correct `use` imports and any code changes needed in the original file.\n\n"
        )

    # 4. Dependency Guard: List what exists
    created_paths = _get_all_created_files(previous_attempts)
    if created_paths:
        paths_str = ", ".join(f"`{p}`" for p in created_paths)
        context += (
            f"CRITICAL — FILES ALREADY CREATED: You have already created {paths_str}. "
            "These files are in the sandbox RIGHT NOW. DO NOT emit another create_file for them. "
            "Focus on fixing the main file to use these new dependencies correctly.\n\n"
        )

    # 5. Mutation score guidance
    last_attempt = previous_attempts[-1]
    if last_attempt.get("failure_reason") == "mutation_failed":
        mutation_details = last_attempt.get("failure_details", "")
        context += (
            f"CRITICAL - MUTATION GATE FAILED: {mutation_details}\n"
            "Your code passed the functional test but is too brittle. "
            "To pass mutation testing, you MUST:\n"
            "  - Use GENERAL logic instead of hardcoded values\n"
            "  - Avoid specific equality checks like `$id == 5` unless absolutely required\n"
            "  - Ensure the logic handles multiple scenarios\n\n"
        )

    return context.strip()


async def escalate_empty_patch(submission_id: str, iteration: int, raw_response: str):
    """
    Called when the AI returns a valid-looking XML block but with ZERO <file> tags.
    This usually means it's stuck or refusing to output code.
    """
    import logging
    logger = logging.getLogger(__name__)
    logger.error(f"[{submission_id}] ESCALATION: AI returned zero patches in iteration {iteration}")
    # In a real system, we might alert a human or try a "nuclear" prompt reset.
    # For now, we just log it; the orchestrator will raise PatchApplicationError.


