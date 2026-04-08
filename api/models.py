"""
api/models.py — SQLAlchemy ORM models for the repair platform.

Two tables:
  - Submission: one row per user code submission
  - Iteration:  one row per repair loop iteration
"""
import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Integer, Float, Text, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return str(uuid.uuid4())


class Submission(Base):
    __tablename__ = "submissions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)
    original_code: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending"
    )  # pending | running | success | failed
    total_iterations: Mapped[int] = mapped_column(Integer, default=0)
    final_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

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
    patch_applied: Mapped[str | None] = mapped_column(Text, nullable=True)
    pest_test_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    pest_test_result: Mapped[str | None] = mapped_column(Text, nullable=True)
    mutation_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)

    submission: Mapped["Submission"] = relationship("Submission", back_populates="iterations")
