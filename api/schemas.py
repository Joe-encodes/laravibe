"""
api/schemas.py — Pydantic v2 request/response schemas.

Naming conventions:
  *Request  — inbound API payload
  *Response — outbound API response (including 202 Accepted)
  *Item     — lightweight list-view shape (no nested relations)
"""
from __future__ import annotations
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, field_validator


class RepairRequest(BaseModel):
    code: str = Field(..., description="The broken PHP/Laravel code to repair")
    prompt: Optional[str] = Field(None, description="Optional custom prompt/context to guide the AI before it repairs")
    max_iterations: Optional[int] = Field(
        default=None, ge=1, le=7,
        description="Max repair iterations (1-7). Defaults to server MAX_ITERATIONS config."
    )
    use_boost: Optional[bool] = Field(True, description="Fetch Laravel Boost context for each iteration")
    use_mutation_gate: Optional[bool] = Field(True, description="Enforce mutation test score threshold")

    @field_validator("code")
    @classmethod
    def validate_php_code(cls, v: str) -> str:
        """Ensure code is non-empty and has a PHP opening tag."""
        if not v.strip():
            raise ValueError("code must not be empty")
        if not v.strip().startswith("<?php"):
            v = "<?php\n" + v
        return v


class RepairAcceptedResponse(BaseModel):
    """202 Accepted — repair has been queued."""
    submission_id: str
    status: str = "pending"
    message: str = "Repair queued. Connect to the stream endpoint for live progress."


class IterationResponse(BaseModel):
    """Full snapshot of a single repair iteration."""
    id: str
    iteration_num: int
    status: str
    error_logs: Optional[str] = None
    boost_context: Optional[str] = None
    patch_applied: Optional[str] = None
    ai_prompt: Optional[str] = None
    ai_response: Optional[str] = None
    pest_test_code: Optional[str] = None
    pest_test_result: Optional[str] = None
    mutation_score: Optional[float] = None
    duration_ms: Optional[int] = None
    created_at: datetime
    model_config = {"from_attributes": True}


class SubmissionResponse(BaseModel):
    """Full submission result including all iteration snapshots."""
    id: str
    status: str
    created_at: datetime
    total_iterations: int
    original_code: str
    user_prompt: Optional[str] = None
    final_code: Optional[str] = None
    error_summary: Optional[str] = None
    case_id: Optional[str] = None
    category: Optional[str] = None
    experiment_id: Optional[str] = None
    iterations: list[IterationResponse] = []
    model_config = {"from_attributes": True}


class HistoryItem(BaseModel):
    """Lightweight submission shape for history list views."""
    id: str
    status: str
    created_at: datetime
    total_iterations: int
    user_prompt: Optional[str] = None
    error_summary: Optional[str] = None
    case_id: Optional[str] = None
    category: Optional[str] = None
    experiment_id: Optional[str] = None
    model_config = {"from_attributes": True}


class HealthResponse(BaseModel):
    status: str = "ok"
    docker: str = "unknown"
    ai: str = "unknown"
    db: str = "unknown"


class EvaluateCaseResult(BaseModel):
    sample_file: str
    status: str
    iterations: int
    mutation_score: Optional[float] = None
    duration_s: float
    submission_id: Optional[str] = None


class EvaluateBatchResponse(BaseModel):
    """Response for POST /api/evaluate — includes experiment tracking ID."""
    experiment_id: Optional[str] = None
    status: Optional[str] = None
    total_cases: int
    success_count: int
    success_rate_pct: float
    cases: list[EvaluateCaseResult]
