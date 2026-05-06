"""
api/schemas.py — Pydantic v2 request/response models.
"""
from __future__ import annotations
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, field_validator


class RepairRequest(BaseModel):
    code: str = Field(..., description="The broken PHP/Laravel code to repair")
    max_iterations: Optional[int] = Field(None, ge=1, le=10)
    use_boost: Optional[bool] = Field(True, description="Whether to fetch context from Laravel Boost")
    use_mutation_gate: Optional[bool] = Field(True, description="Whether to run mutation tests")
    prompt: Optional[str] = Field(None, description="Optional custom instruction prompt for the repair loop")

    @field_validator("code")
    @classmethod
    def code_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("code must not be empty")
        return v

    @field_validator("code")
    @classmethod
    def validate_php_code(cls, v: str) -> str:
        # Basic validation to ensure it looks like PHP
        if not v.strip().startswith("<?php"):
            v = "<?php\n" + v
        return v


class RepairSubmitResponse(BaseModel):
    submission_id: str
    status: str = "pending"
    message: str = "Repair queued. Connect to the stream endpoint for live progress."


class IterationOut(BaseModel):
    id: str
    iteration_num: int
    status: str
    error_logs: Optional[str] = None
    patch_applied: Optional[str] = None
    ai_prompt: Optional[str] = None
    ai_response: Optional[str] = None
    pest_test_code: Optional[str] = None
    pest_test_result: Optional[str] = None
    mutation_score: Optional[float] = None
    duration_ms: Optional[int] = None
    pipeline_logs: Optional[str] = None
    created_at: datetime
    model_config = {"from_attributes": True}


class SubmissionOut(BaseModel):
    id: str
    status: str
    created_at: datetime
    total_iterations: int
    original_code: str
    final_code: Optional[str] = None
    error_summary: Optional[str] = None
    is_cancelled: bool = False
    container_id: Optional[str] = None
    case_id: Optional[str] = None
    category: Optional[str] = None
    experiment_id: Optional[str] = None
    iterations: list[IterationOut] = []
    model_config = {"from_attributes": True}


class HistoryItem(BaseModel):
    id: str
    status: str
    created_at: datetime
    total_iterations: int
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


class EvaluateResponse(BaseModel):
    total_cases: int
    success_count: int
    success_rate_pct: float
    cases: list[EvaluateCaseResult]
    experiment_id: Optional[str] = None
    status: Optional[str] = None
