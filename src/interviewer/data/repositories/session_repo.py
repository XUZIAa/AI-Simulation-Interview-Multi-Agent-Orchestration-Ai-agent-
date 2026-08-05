from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from ...core.types import InterviewPhase, SessionStatus, Speaker, TurnIntent
from ...domain.interview import InterviewState, QuestionRecord, TurnRecord
from ...domain.persona import PersonaContract
from ..models import QuestionRow, SessionRow, TurnRow
from .base import Repository, chunked

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class SessionSummary:
    id: int
    title: str
    status: SessionStatus
    persona_name: str
    created_at: datetime
    duration_ms: int
    overall_score: float | None
    planned_minutes: int


@dataclass(slots=True)
class GlobalStats:
    total_sessions: int
    completed_sessions: int
    total_minutes: int
    best_score: float | None
    latest_score: float | None
    average_score: float | None


class SessionRepository(Repository):
    async def create(
        self,
        *,
        title: str,
        persona: PersonaContract,
        planned_minutes: int,
        resume_id: int | None,
        job_id: int | None,
    ) -> int:
        async with self.db.transaction() as session:
            row = SessionRow(
                title=title,
                status=SessionStatus.DRAFT.value,
                persona_id=persona.id,
                persona_name=persona.name,
                resume_id=resume_id,
                job_id=job_id,
                planned_minutes=planned_minutes,
                state={},
            )
            session.add(row)
            await session.flush()
            return row.id

    async def set_status(self, session_id: int, status: SessionStatus) -> None:
        values: dict[str, object] = {"status": status.value}
        if status is SessionStatus.RUNNING:
            values["started_at"] = datetime.now(UTC)
        elif status in (SessionStatus.COMPLETED, SessionStatus.ABORTED):
            values["ended_at"] = datetime.now(UTC)
        async with self.db.transaction() as session:
            await session.execute(update(SessionRow).where(SessionRow.id == session_id).values(**values))

    async def persist_state(self, state: InterviewState) -> None:
        payload = state.model_dump(mode="json")
        async with self.db.transaction() as session:
            await session.execute(
                update(SessionRow)
                .where(SessionRow.id == state.session_id)
                .values(state=payload, duration_ms=state.elapsed_ms)
            )

    async def load_state(self, session_id: int) -> InterviewState | None:
        async with self.db.session() as session:
            row = await session.get(SessionRow, session_id)
        if row is None or not row.state:
            return None
        return InterviewState.model_validate(row.state)

    @staticmethod
    def _turn_stmt(session_id: int, turn: TurnRecord):
        return (
            sqlite_insert(TurnRow)
            .values(
                session_id=session_id,
                turn_index=turn.index,
                speaker=turn.speaker.value,
                text=turn.text,
                started_at_ms=turn.started_at_ms,
                duration_ms=turn.duration_ms,
                intent=turn.intent.value if turn.intent else "",
                was_interrupted=turn.was_interrupted,
                question_index=turn.question_index,
            )
            .on_conflict_do_update(
                index_elements=["session_id", "turn_index"],
                set_={
                    "text": turn.text,
                    "duration_ms": turn.duration_ms,
                    "was_interrupted": turn.was_interrupted,
                    "question_index": turn.question_index,
                },
            )
        )

    @staticmethod
    def _question_stmt(session_id: int, question: QuestionRecord):
        return (
            sqlite_insert(QuestionRow)
            .values(
                session_id=session_id,
                question_index=question.index,
                phase=question.phase.value,
                intent=question.intent.value,
                brief=question.brief,
                target_skill=question.target_skill,
                spoken_text=question.spoken_text,
                answer_text=question.answer_text,
                asked_at_ms=question.asked_at_ms,
                follow_up_depth=question.follow_up_depth,
                quality=question.quality,
            )
            .on_conflict_do_update(
                index_elements=["session_id", "question_index"],
                set_={
                    "spoken_text": question.spoken_text,
                    "answer_text": question.answer_text,
                    "quality": question.quality,
                },
            )
        )

    async def upsert_turn(self, session_id: int, turn: TurnRecord) -> None:
        async with self.db.transaction() as session:
            await session.execute(self._turn_stmt(session_id, turn))

    async def upsert_question(self, session_id: int, question: QuestionRecord) -> None:
        async with self.db.transaction() as session:
            await session.execute(self._question_stmt(session_id, question))

    async def sync_records(self, state: InterviewState) -> None:
        """收尾时整体对齐一次，按批提交。

        必须走自然键 upsert：这些行在面试过程中已逐条写入过，
        用 merge 插新对象会撞 (session_id, question_index) 唯一约束。
        """
        for batch in chunked(state.questions):
            async with self.db.transaction() as session:
                for question in batch:
                    await session.execute(self._question_stmt(state.session_id, question))
        for batch in chunked(state.turns):
            async with self.db.transaction() as session:
                for turn in batch:
                    await session.execute(self._turn_stmt(state.session_id, turn))

    async def load_turns(self, session_id: int) -> list[TurnRecord]:
        async with self.db.session() as session:
            stmt = select(TurnRow).where(TurnRow.session_id == session_id).order_by(TurnRow.turn_index)
            rows = (await session.execute(stmt)).scalars().all()
        return [
            TurnRecord(
                index=r.turn_index,
                speaker=Speaker(r.speaker),
                text=r.text,
                started_at_ms=r.started_at_ms,
                duration_ms=r.duration_ms,
                was_interrupted=r.was_interrupted,
                question_index=r.question_index,
            )
            for r in rows
        ]

    async def load_questions(self, session_id: int) -> list[QuestionRecord]:
        async with self.db.session() as session:
            stmt = (
                select(QuestionRow)
                .where(QuestionRow.session_id == session_id)
                .order_by(QuestionRow.question_index)
            )
            rows = (await session.execute(stmt)).scalars().all()
        return [
            QuestionRecord(
                index=r.question_index,
                phase=InterviewPhase(r.phase),
                intent=TurnIntent(r.intent) if r.intent else TurnIntent.ASK_NEW,
                brief=r.brief,
                target_skill=r.target_skill,
                spoken_text=r.spoken_text,
                answer_text=r.answer_text,
                asked_at_ms=r.asked_at_ms,
                follow_up_depth=r.follow_up_depth,
                quality=r.quality,
            )
            for r in rows
        ]

    async def finish(self, session_id: int, *, duration_ms: int, audio_path: str = "") -> None:
        async with self.db.transaction() as session:
            await session.execute(
                update(SessionRow)
                .where(SessionRow.id == session_id)
                .values(duration_ms=duration_ms, audio_path=audio_path, ended_at=datetime.now(UTC))
            )

    async def set_score(self, session_id: int, overall: float) -> None:
        async with self.db.transaction() as session:
            await session.execute(
                update(SessionRow).where(SessionRow.id == session_id).values(overall_score=overall)
            )

    async def list_recent(self, limit: int = 50) -> list[SessionSummary]:
        async with self.db.session() as session:
            stmt = select(SessionRow).order_by(SessionRow.created_at.desc()).limit(limit)
            rows = (await session.execute(stmt)).scalars().all()
        return [
            SessionSummary(
                id=r.id,
                title=r.title,
                status=SessionStatus(r.status),
                persona_name=r.persona_name,
                created_at=r.created_at,
                duration_ms=r.duration_ms,
                overall_score=r.overall_score,
                planned_minutes=r.planned_minutes,
            )
            for r in rows
        ]

    async def stats(self) -> GlobalStats:
        async with self.db.session() as session:
            total = (await session.execute(select(func.count(SessionRow.id)))).scalar_one()
            completed_stmt = select(func.count(SessionRow.id)).where(
                SessionRow.status == SessionStatus.COMPLETED.value
            )
            completed = (await session.execute(completed_stmt)).scalar_one()
            duration = (await session.execute(select(func.sum(SessionRow.duration_ms)))).scalar_one() or 0
            best = (await session.execute(select(func.max(SessionRow.overall_score)))).scalar_one()
            avg = (await session.execute(select(func.avg(SessionRow.overall_score)))).scalar_one()
            latest_stmt = (
                select(SessionRow.overall_score)
                .where(SessionRow.overall_score.is_not(None))
                .order_by(SessionRow.created_at.desc())
                .limit(1)
            )
            latest = (await session.execute(latest_stmt)).scalar_one_or_none()
        return GlobalStats(
            total_sessions=int(total),
            completed_sessions=int(completed),
            total_minutes=int(duration // 60_000),
            best_score=best,
            latest_score=latest,
            average_score=avg,
        )

    async def delete(self, session_id: int) -> None:
        async with self.db.transaction() as session:
            await session.execute(delete(SessionRow).where(SessionRow.id == session_id))
