from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, ClassVar

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from ..core.types import SessionStatus


def _now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    type_annotation_map: ClassVar[dict[Any, Any]] = {dict[str, Any]: JSON, list[Any]: JSON}


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class PersonaRow(Base, TimestampMixin):
    __tablename__ = "personas"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), index=True)
    archetype: Mapped[str] = mapped_column(String(40))
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    usage_count: Mapped[int] = mapped_column(Integer, default=0)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)

    __table_args__ = (UniqueConstraint("name", name="uq_persona_name"),)


class ResumeRow(Base, TimestampMixin):
    __tablename__ = "resumes"

    id: Mapped[int] = mapped_column(primary_key=True)
    label: Mapped[str] = mapped_column(String(120), index=True)
    file_path: Mapped[str] = mapped_column(String(500), default="")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class JobRow(Base, TimestampMixin):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    label: Mapped[str] = mapped_column(String(120), index=True)
    company: Mapped[str] = mapped_column(String(120), default="")
    title: Mapped[str] = mapped_column(String(120), default="")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class GapReportRow(Base, TimestampMixin):
    __tablename__ = "gap_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    resume_id: Mapped[int] = mapped_column(ForeignKey("resumes.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    match_score: Mapped[int] = mapped_column(Integer, default=0)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)

    __table_args__ = (Index("ix_gap_pair", "resume_id", "job_id"),)


class SessionRow(Base, TimestampMixin):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[str] = mapped_column(String(20), default=SessionStatus.DRAFT.value, index=True)
    persona_id: Mapped[int | None] = mapped_column(
        ForeignKey("personas.id", ondelete="SET NULL"), nullable=True
    )
    persona_name: Mapped[str] = mapped_column(String(64), default="")
    resume_id: Mapped[int | None] = mapped_column(
        ForeignKey("resumes.id", ondelete="SET NULL"), nullable=True
    )
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)
    planned_minutes: Mapped[int] = mapped_column(Integer, default=35)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    overall_score: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    audio_path: Mapped[str] = mapped_column(String(500), default="")
    state: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    turns: Mapped[list[TurnRow]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="TurnRow.turn_index"
    )
    questions: Mapped[list[QuestionRow]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="QuestionRow.question_index"
    )
    review: Mapped[ReviewRow | None] = relationship(
        back_populates="session", cascade="all, delete-orphan", uselist=False
    )


class TurnRow(Base):
    __tablename__ = "turns"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    turn_index: Mapped[int] = mapped_column(Integer)
    speaker: Mapped[str] = mapped_column(String(16), index=True)
    text: Mapped[str] = mapped_column(Text, default="")
    started_at_ms: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    intent: Mapped[str] = mapped_column(String(24), default="")
    was_interrupted: Mapped[bool] = mapped_column(Boolean, default=False)
    question_index: Mapped[int | None] = mapped_column(Integer, nullable=True)

    session: Mapped[SessionRow] = relationship(back_populates="turns")

    __table_args__ = (UniqueConstraint("session_id", "turn_index", name="uq_turn_seq"),)


class QuestionRow(Base):
    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    question_index: Mapped[int] = mapped_column(Integer)
    phase: Mapped[str] = mapped_column(String(24), index=True)
    intent: Mapped[str] = mapped_column(String(24), default="")
    brief: Mapped[str] = mapped_column(Text, default="")
    target_skill: Mapped[str] = mapped_column(String(120), default="", index=True)
    spoken_text: Mapped[str] = mapped_column(Text, default="")
    answer_text: Mapped[str] = mapped_column(Text, default="")
    asked_at_ms: Mapped[int] = mapped_column(Integer, default=0)
    follow_up_depth: Mapped[int] = mapped_column(Integer, default=0)
    quality: Mapped[float | None] = mapped_column(Float, nullable=True)

    session: Mapped[SessionRow] = relationship(back_populates="questions")

    __table_args__ = (UniqueConstraint("session_id", "question_index", name="uq_question_seq"),)


class ReviewRow(Base, TimestampMixin):
    __tablename__ = "reviews"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), unique=True, index=True
    )
    overall_score: Mapped[float] = mapped_column(Float, default=0.0)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)

    session: Mapped[SessionRow] = relationship(back_populates="review")


class MistakeRow(Base, TimestampMixin):
    __tablename__ = "mistakes"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int | None] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), nullable=True, index=True
    )
    knowledge_point: Mapped[str] = mapped_column(String(160), index=True)
    topic: Mapped[str] = mapped_column(String(80), default="", index=True)
    question: Mapped[str] = mapped_column(Text, default="")
    candidate_answer: Mapped[str] = mapped_column(Text, default="")
    key_points: Mapped[list[Any]] = mapped_column(JSON, default=list)
    severity: Mapped[str] = mapped_column(String(16), default="major", index=True)
    review_hint: Mapped[str] = mapped_column(Text, default="")
    hit_count: Mapped[int] = mapped_column(Integer, default=1)
    mastered: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class SkillTrendRow(Base):
    """每场面试落一行维度分，成长曲线直接按此聚合，避免解析大 JSON。"""

    __tablename__ = "skill_trends"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    dimension: Mapped[str] = mapped_column(String(24), index=True)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)

    __table_args__ = (UniqueConstraint("session_id", "dimension", name="uq_trend_point"),)
