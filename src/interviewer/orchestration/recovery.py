from __future__ import annotations

import logging
from dataclasses import dataclass

from ..core.types import SessionStatus
from ..data.repositories.session_repo import SessionRepository
from ..domain.interview import InterviewState

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class InterruptedSession:
    session_id: int
    title: str
    duration_ms: int
    reviewable: bool


class RecoveryService:
    """崩溃或强退后的兜底。每轮都落了盘，所以记录不会丢，只需要认领。"""

    def __init__(self, sessions: SessionRepository) -> None:
        self._sessions = sessions

    async def scan(self) -> list[InterruptedSession]:
        summaries = await self._sessions.list_recent(limit=40)
        stale = [s for s in summaries if s.status is SessionStatus.RUNNING]
        results: list[InterruptedSession] = []
        for summary in stale:
            state = await self._sessions.load_state(summary.id)
            duration = state.elapsed_ms if state else summary.duration_ms
            results.append(
                InterruptedSession(
                    session_id=summary.id,
                    title=summary.title,
                    duration_ms=duration,
                    reviewable=bool(state and state.reviewable),
                )
            )
            await self._sessions.set_status(summary.id, SessionStatus.REVIEWING)
            logger.info("发现中断的面试 session=%s 时长=%dms", summary.id, duration)
        return results

    async def load_state(self, session_id: int) -> InterviewState | None:
        state = await self._sessions.load_state(session_id)
        if state is None:
            return None
        # 逐轮落盘比整体状态落盘更频繁，用表数据补齐可能缺失的尾部
        turns = await self._sessions.load_turns(session_id)
        if len(turns) >= len(state.turns):
            state.turns = turns
            state.turn_index = max((t.index for t in turns), default=state.turn_index)
        questions = await self._sessions.load_questions(session_id)
        if len(questions) > len(state.questions):
            merged = {q.index: q for q in state.questions}
            for question in questions:
                existing = merged.get(question.index)
                if existing is None:
                    merged[question.index] = question
                else:
                    existing.spoken_text = existing.spoken_text or question.spoken_text
                    existing.answer_text = existing.answer_text or question.answer_text
            state.questions = [merged[k] for k in sorted(merged)]
        return state
