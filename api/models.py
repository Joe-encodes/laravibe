"""
api/models.py — SQLAlchemy ORM models for the repair platform.

Two tables:
  - Submission: one row per user code submission
  - Iteration:  one row per repair loop iteration
"""
import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Integer, Float, Text, DateTime, ForeignKey, Index, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return str(uuid.uuid4())


class Submission(Base):
    __tablename__ = "submissions"
    __table_args__ = (
        Index("idx_submissions_status_created", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)
    original_code: Mapped[str] = mapped_column(Text, nullable=False)
    user_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending"
    )  # pending | running | success | failed
    total_iterations: Mapped[int] = mapped_column(Integer, default=0)
    final_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_cancelled: Mapped[bool] = mapped_column(Boolean, default=False)
    container_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Research Metadata
    case_id: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    category: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    experiment_id: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)

    iterations: Mapped[list["Iteration"]] = relationship(
        "Iteration", back_populates="submission", cascade="all, delete-orphan"
    )


class Iteration(Base):
    __tablename__ = "iterations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    submission_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("submissions.id"), nullable=False
    )
    iteration_num: Mapped[int] = mapped_column(Integer, nullable=False)
    code_input: Mapped[str] = mapped_column(Text, nullable=False)
    execution_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_logs: Mapped[str | None] = mapped_column(Text, nullable=True)
    boost_context: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_model_used: Mapped[str | None] = mapped_column(String(100), nullable=True)  # legacy single-model field
    # Role pipeline model tracking (populated when USE_ROLE_PIPELINE=true)
    planner_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    executor_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    reviewer_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    patch_applied: Mapped[str | None] = mapped_column(Text, nullable=True)
    pest_test_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    pest_test_result: Mapped[str | None] = mapped_column(Text, nullable=True)
    mutation_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Failure tracking for better feedback loop
    failure_reason: Mapped[str | None] = mapped_column(String(100), nullable=True)  # "pest_failed" | "mutation_failed" | "patch_failed" | "test_syntax_error"
    failure_details: Mapped[str | None] = mapped_column(Text, nullable=True)  # Structured info about why it failed
    pm_category: Mapped[str | None] = mapped_column(String(50), nullable=True)  # Post-mortem category from critic: "syntax" | "logic" | "dependency" | "database" | "test"
    pm_strategy: Mapped[str | None] = mapped_column(Text, nullable=True)  # Post-mortem fix strategy
    pipeline_logs: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list of all SSE events for this iteration
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)

    submission: Mapped["Submission"] = relationship("Submission", back_populates="iterations")


class RepairSummary(Base):
    """
    Stores successful repairs (Phase 7).
    When a future defect exhibits the same error_type, we retrieve
    relevant summaries to show the AI how this error was fixed before.
    """
    __tablename__ = "repair_summaries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    error_type: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    diagnosis: Mapped[str] = mapped_column(Text, nullable=False)
    fix_applied: Mapped[str] = mapped_column(Text, nullable=False)
    what_did_not_work: Mapped[str | None] = mapped_column(Text, nullable=True)
    iterations_needed: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)
