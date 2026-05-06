"""
api/services/error_classifier.py — Structured error classification.

Instead of passing raw error logs to the LLM, we pre-classify them into
structured categories so the LLM gets clean, actionable information.

Categories:
  - MISSING_METHOD: Call to undefined method
  - UNDEFINED_VAR: Undefined variable or property
  - MISSING_IMPORT: Class/interface not found
  - SYNTAX_ERROR: PHP parse error
  - WRONG_TYPE: Type mismatch or invalid argument
  - DATABASE_ERROR: Migration or DB operation failed
  - PEST_FAILURE: Functional test assertion failure
  - CLASS_REDECLARATION: Fatal error declaring same class twice
  - LOGIC_ERROR: No parse/runtime error but behavior is wrong
  - UNKNOWN: Couldn't classify
"""
import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class ClassifiedError:
    """Structured error information."""
    category: str  # MISSING_METHOD | UNDEFINED_VAR | MISSING_IMPORT | SYNTAX_ERROR | etc.
    summary: str  # One-line summary
    details: dict  # Category-specific details
    full_trace: str  # Original error logs for context


def classify_error(error_logs: str) -> ClassifiedError:
    """
    Classify a raw error log into a structured error type.
    Returns ClassifiedError with category and extracted details.
    """
    print(f"DEBUG: classify_error input: '{error_logs}' (len={len(error_logs)})")
    if not error_logs or not error_logs.strip():
        print("DEBUG: Returning NONE")
        return ClassifiedError(
            category="NONE",
            summary="No errors detected during discovery.",
            details={},
            full_trace=""
        )

    # Truncate very long traces to save tokens (Hardening Phase 1)
    max_trace = 1500
    if len(error_logs) > max_trace:
        error_logs = error_logs[:max_trace] + f"\n... [TRUNCATED {len(error_logs) - max_trace} chars]"

    # Lowercase for case-insensitive matching
    logs_lower = error_logs.lower()

    # ── CLASS REDECLARATION (Priority 1) ──────────────────────────────────────
    if "already in use" in logs_lower or "cannot declare class" in logs_lower:
        # Improved regex to handle 'App\Models\User' followed by a comma or space
        m = re.search(r"class ([\w\\]+)[,\s]", error_logs, re.IGNORECASE)
        class_name = m.group(1) if m else "Unknown"
        return ClassifiedError(
            category="CLASS_REDECLARATION",
            summary=f"Fatal Error: Class {class_name} redeclared (Check for duplicate files in container)",
            details={"class": class_name, "type": "fatal_redecl"},
            full_trace=error_logs
        )

    # ── PEST FAILURE / ASSERTIONS (Priority 2) ────────────────────────────────
    # Patterns: "FAILED", "Failed asserting that", "Expected ... but got ..."
    if "failed" in logs_lower and any(p in logs_lower for p in ["asserting that", "expected", "pest"]):
        m = re.search(r"Failed asserting that (.*)", error_logs, re.IGNORECASE)
        assertion = m.group(1).strip() if m else "Logic assertion failed"
        return ClassifiedError(
            category="PEST_FAILURE",
            summary=f"Test failed: {assertion[:100]}",
            details={"type": "assertion_failure", "assertion": assertion},
            full_trace=error_logs
        )

    # ── MISSING_METHOD ────────────────────────────────────────────────────────
    m = re.search(
        r"(?:Call to undefined method|Method\s+[\w\\]+::\w+\s+does not exist)\s+([\\A-Za-z0-9_]+)::(\w+)\(\)",
        error_logs,
        re.IGNORECASE
    )
    if m:
        class_name = m.group(1).split("\\")[-1]
        method_name = m.group(2)
        return ClassifiedError(
            category="MISSING_METHOD",
            summary=f"Method {method_name}() not found in class {class_name}",
            details={
                "class": class_name,
                "method": method_name,
                "type": "method_missing"
            },
            full_trace=error_logs
        )

    # ── UNDEFINED VARIABLE ────────────────────────────────────────────────────
    m = re.search(
        r"Undefined (?:variable|property)\s+\$?(\w+)",
        error_logs,
        re.IGNORECASE
    )
    if m:
        var_name = m.group(1)
        return ClassifiedError(
            category="UNDEFINED_VAR",
            summary=f"Variable or property ${var_name} is undefined",
            details={
                "variable": var_name,
                "type": "undefined"
            },
            full_trace=error_logs
        )

    # ── SYNTAX_ERROR ──────────────────────────────────────────────────────────
    m = re.search(
        r"(?:Parse error|Syntax error):.*?(?:in|at)\s+([/\w\\.-]+)\s+(?:on|at)\s+line\s+(\d+)",
        error_logs,
        re.IGNORECASE | re.DOTALL
    )
    if m:
        file_path = m.group(1)
        line_num = m.group(2)
        return ClassifiedError(
            category="SYNTAX_ERROR",
            summary=f"PHP syntax error in {file_path} at line {line_num}",
            details={"file": file_path, "line": line_num, "type": "parse_error"},
            full_trace=error_logs
        )

    # ── MISSING IMPORT / CLASS NOT FOUND ──────────────────────────────────────
    m = re.search(
        r"(?:Class|Interface)\s+'?([\\A-Za-z0-9_]+)'?\s+not found",
        error_logs,
        re.IGNORECASE
    )
    if m:
        class_name = m.group(1)
        return ClassifiedError(
            category="MISSING_IMPORT",
            summary=f"Class or interface {class_name} not found",
            details={
                "class": class_name,
                "type": "missing_class"
            },
            full_trace=error_logs
        )

    # ── DATABASE ERROR ────────────────────────────────────────────────────────
    if any(phrase in logs_lower for phrase in ["sqlstate", "migration", "table", "database", "foreign key"]):
        return ClassifiedError(
            category="DATABASE_ERROR",
            summary="Database or migration error",
            details={"type": "db_error"},
            full_trace=error_logs
        )

    # ── WRONG TYPE / TYPE ERROR (Moved down to avoid Pest overlap) ────────────
    if any(phrase in logs_lower for phrase in ["must be of type", "TypeError"]) or \
       (re.search(r"expects .* got ", error_logs, re.IGNORECASE) and "pest" not in logs_lower):
        return ClassifiedError(
            category="WRONG_TYPE",
            summary="Type mismatch or invalid argument type",
            details={"type": "type_error"},
            full_trace=error_logs
        )

    # ── LOGIC ERROR (Default for unexplained test failures) ───────────────────
    if "expected" in logs_lower or "failed assertion" in logs_lower:
        return ClassifiedError(
            category="LOGIC_ERROR",
            summary="Test failed - logic error in implementation",
            details={"type": "logic_failure"},
            full_trace=error_logs
        )

    # ── DEFAULT: UNKNOWN ──────────────────────────────────────────────────────
    return ClassifiedError(
        category="UNKNOWN",
        summary="Could not classify error. See full trace.",
        details={"type": "unclassified"},
        full_trace=error_logs
    )


def format_classified_error_for_llm(classified: ClassifiedError) -> str:
    """
    Format a ClassifiedError into a clean prompt string for the LLM.
    Gives clean structure and truncates the trace to save tokens.
    """
    lines = [
        f"ERROR CLASSIFICATION: {classified.category}",
        f"Summary: {classified.summary}",
    ]

    if classified.details:
        lines.append("\nDetails:")
        for key, value in classified.details.items():
            if value:
                lines.append(f"  - {key}: {value}")

    # Trace Truncation: Keep the first 1000 and last 500 characters
    trace = classified.full_trace
    if len(trace) > 1500:
        trace = trace[:1000] + "\n\n[... TRUNCATED FOR TOKEN SAVINGS ...]\n\n" + trace[-500:]

    lines.append(f"\nFull Error Trace:\n{trace}")

    return "\n".join(lines)

