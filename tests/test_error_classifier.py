
import pytest
from api.services.error_classifier import classify_error, ClassifiedError

def test_classify_syntax_error():
    logs = "Parse error: syntax error, unexpected 'public' (T_PUBLIC) in app/Models/User.php on line 12"
    result = classify_error(logs)
    assert result.category == "SYNTAX_ERROR"
    assert "app/Models/User.php" in result.summary
    assert result.details["file"] == "app/Models/User.php"

def test_classify_pest_failure():
    logs = "1) Tests\\Feature\\RepairTest\nFailed asserting that 404 matches expected 200."
    result = classify_error(logs)
    # Hardening fix: Pest failures should be PEST_FAILURE, not generic
    assert result.category == "PEST_FAILURE"
    assert "404 matches expected 200" in result.summary

def test_classify_class_redeclaration():
    logs = "Fatal error: Cannot declare class App\\Models\\User, because the name is already in use in ..."
    result = classify_error(logs)
    # Hardening fix: Newly added category
    assert result.category == "CLASS_REDECLARATION"
    assert result.details["class"] == "App\\Models\\User"

def test_classify_truncation():
    # Hardening fix: Truncate very long logs
    long_logs = "A" * 10000
    result = classify_error(long_logs)
    assert len(result.full_trace) < 2000
    assert "[TRUNCATED" in result.full_trace

def test_classify_unknown_junk():
    logs = "Some random text that doesn't look like an error"
    result = classify_error(logs)
    assert result.category == "UNKNOWN"

def test_classify_database_error():
    logs = "SQLSTATE[HY000]: General error: 1 table users already exists"
    result = classify_error(logs)
    assert result.category == "DATABASE_ERROR"
