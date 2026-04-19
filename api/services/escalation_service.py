"""
api/services/escalation_service.py — Stuck loop detection and escalation.

Handles Phase 6: detects when the LLM is stuck in a loop of identical
diagnoses or failing patches, and injects stern instructions.

Escalation triggers:
  1. Repeated identical diagnoses (fuzzy match, threshold=2)
  2. Back-to-back patch application failures
  3. create_file was used but the original file still fails
"""

import re

# Minimum consecutive identical diagnoses before escalation
STUCK_DIAGNOSIS_THRESHOLD = 2


def _get_words(text: str) -> set:
    return set(re.findall(r'\b\w+\b', text.lower()))


def is_fuzzy_match(text1: str, text2: str, threshold: float = 0.70) -> bool:
    w1 = _get_words(text1)
    w2 = _get_words(text2)
    if not w1 or not w2:
        return text1 == text2
    overlap = len(w1.intersection(w2))
    return (overlap / len(w1) >= threshold) and (overlap / len(w2) >= threshold)


def should_force_full_replace(previous_attempts: list[dict]) -> bool:
    """If the LLM has tried to patch twice and failed both times, force full_replace."""
    if len(previous_attempts) < 2:
        return False

    last_two = previous_attempts[-2:]
    return all(a.get("patch_status", "").startswith("FAILED") for a in last_two)


def _last_action_was_create_file(previous_attempts: list[dict]) -> bool:
    """Check if the most recent action included create_file but NOT full_replace."""
    if not previous_attempts:
        return False
    last_action = previous_attempts[-1].get("action", "")
    return "create_file" in last_action and "full_replace" not in last_action


def build_escalation_context(previous_attempts: list[dict]) -> str:
    """Build a stern prompt piece when the LLM is stuck."""
    context = ""

    # 1. Stuck diagnoses (fuzzy match) — trigger after just 2 identical
    if len(previous_attempts) >= STUCK_DIAGNOSIS_THRESHOLD:
        window = previous_attempts[-STUCK_DIAGNOSIS_THRESHOLD:]
        recent = [a.get("diagnosis", "") for a in window]
        recent = [d for d in recent if d.strip()]

        if len(recent) >= STUCK_DIAGNOSIS_THRESHOLD:
            all_same = all(is_fuzzy_match(recent[0], d) for d in recent[1:])

            if all_same:
                context += (
                    f"CRITICAL: Your last {len(recent)} diagnoses were essentially IDENTICAL.\n"
                    f"You keep diagnosing: '{recent[0]}'.\n"
                    "This approach is NOT WORKING. You MUST try a completely different logical approach. "
                    "Stop repeating the same reasoning.\n\n"
                )

    # 2. Patch failures
    if should_force_full_replace(previous_attempts):
        context += (
            "CRITICAL: Your recent patches failed to apply because the 'target' text was not found.\n"
            "DO NOT use action='replace' anymore for this file. You MUST use action='full_replace' "
            "and output the entire complete corrected file.\n\n"
        )

    # 3. create_file without fixing the original file
    if _last_action_was_create_file(previous_attempts):
        context += (
            "IMPORTANT: In the previous iteration you created a dependency file (e.g. a Model or Migration) "
            "but you did NOT fix the original submitted controller/class file.\n"
            "The dependency file now EXISTS in the sandbox. Your ONLY job now is to output a `full_replace` "
            "patch for the original submitted file. Do NOT create the dependency again.\n"
            "Include BOTH the correct `use` imports and any code changes needed in the original file.\n\n"
        )

    return context.strip()
