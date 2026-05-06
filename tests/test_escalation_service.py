
import pytest
from api.services.escalation_service import build_escalation_context, should_force_full_replace

def test_escalation_stuck_detection():
    # Scenario: 3 iterations with the exact same failure
    history = [
        {"iteration": 1, "failure_reason": "pest_failed", "diagnosis": "broken"},
        {"iteration": 2, "failure_reason": "pest_failed", "diagnosis": "broken"},
        {"iteration": 3, "failure_reason": "pest_failed", "diagnosis": "broken"},
    ]
    ctx = build_escalation_context(history)
    assert "SAME FAILURE" in ctx
    assert "Attempt 3" in ctx

def test_escalation_diverse_failures():
    # Scenario: Different failures
    history = [
        {"iteration": 1, "failure_reason": "syntax_error", "failure_details": "missing brace"},
        {"iteration": 2, "failure_reason": "pest_failed", "failure_details": "assertion failed"},
    ]
    ctx = build_escalation_context(history)
    assert "Attempt 2" in ctx
    assert "pest_failed" in ctx
    assert "SAME FAILURE" not in ctx

def test_force_full_replace_logic():
    # Hardening fix: should_force_full_replace requires 2 failures for 'back-to-back'
    history = [
        {"failure_reason": "patch_failed"},
        {"failure_reason": "patch_failed"}
    ]
    assert should_force_full_replace(history) is True
    
    history = [{"failure_reason": "patch_failed"}]
    assert should_force_full_replace(history) is False


def test_history_lookback_limit():
    # Hardening fix: max_lookback should only consider recent attempts
    # We use 3 attempts with same diagnosis to trigger 'SAME FAILURE'
    history = [{"iteration": i, "diagnosis": "broken"} for i in range(1, 10)]
    ctx = build_escalation_context(history)
    assert "SAME FAILURE" in ctx

def test_fuzzy_match_logic():
    from api.services.escalation_service import is_fuzzy_match
    assert is_fuzzy_match("The model is missing", "Missing model") is True
    assert is_fuzzy_match("The model is missing", "Syntax error") is False
    assert is_fuzzy_match("", "") is True
    assert is_fuzzy_match("abc", "abc") is True

def test_dependency_tracking():
    from api.services.escalation_service import _last_action_included_create_file, _get_all_created_files
    history = [
        {"files": ["app/Models/User.php"]},
        {"files": []}
    ]
    assert _last_action_included_create_file(history) is False
    assert "app/Models/User.php" in _get_all_created_files(history)
    
    history = [{"files": ["app/Models/Product.php"]}]
    assert _last_action_included_create_file(history) is True

def test_mutation_guidance_injection():
    history = [
        {"failure_reason": "mutation_failed", "failure_details": "killed 2/10"}
    ]
    ctx = build_escalation_context(history)
    assert "MUTATION GATE FAILED" in ctx
    assert "killed 2/10" in ctx

@pytest.mark.asyncio
async def test_escalate_empty_patch_logs():
    from api.services.escalation_service import escalate_empty_patch
    # Should just run without error
    await escalate_empty_patch("sub-1", 1, "<repair></repair>")
