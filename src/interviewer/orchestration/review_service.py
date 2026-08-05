from __future__ import annotations

import logging

from ..agents.reviewer import Reviewer
from ..analysis import prosody, transcript
from ..core.events import EventBus, ProsodySnapshot, ReviewProgress
from ..core.types import SessionStatus
from ..data.repositories.review_repo import ReviewRepository
from ..data.repositories.session_repo import SessionRepository
from ..domain.interview import InterviewState
from ..domain.review import ReviewReport
from ..llm.router import LLMRouter

logger = logging.getLogger(__name__)


class ReviewService:
    """面试后的离线复盘。客观指标先算好，模型只负责解读。"""

    def __init__(
        self,
        *,
        bus: EventBus,
        router: LLMRouter,
        sessions: SessionRepository,
        reviews: ReviewRepository,
    ) -> None:
        self._bus = bus
        self._reviewer = Reviewer(router)
        self._sessions = sessions
        self._reviews = reviews

    async def generate(self, state: InterviewState) -> ReviewReport:
        self._emit("prosody", 5, "正在分析语速与停顿")
        prosody_report = prosody.analyze(state.turns, total_duration_ms=state.elapsed_ms)
        self._bus.emit(
            ProsodySnapshot(
                words_per_minute=prosody_report.words_per_minute,
                filler_ratio=prosody_report.filler_ratio,
                pause_ratio=prosody_report.pause_ratio,
                longest_pause_ms=prosody_report.longest_pause_ms,
            )
        )

        self._emit("transcript", 12, "正在整理逐字稿")
        turns_text = transcript.format_turns(state.turns)
        questions_text = transcript.format_questions(state.questions)

        report = await self._reviewer.compose(
            state,
            transcript=turns_text,
            question_digest=questions_text,
            coding_summary=transcript.coding_summary(state),
            prosody=prosody_report,
            prosody_summary=prosody.summary_for_model(prosody_report),
            on_progress=self._emit,
        )

        self._emit("persist", 96, "正在保存复盘结果")
        await self._reviews.save_review(report)
        await self._sessions.set_status(state.session_id, SessionStatus.COMPLETED)
        self._emit("done", 100, "复盘已生成")
        logger.info(
            "复盘完成 session=%s 总分=%.1f 错题=%d 专项=%d",
            state.session_id,
            report.overall_score,
            len(report.mistakes),
            len(report.improvement_plans),
        )
        return report

    async def load(self, session_id: int) -> ReviewReport | None:
        return await self._reviews.get_review(session_id)

    def _emit(self, stage: str, percent: int, detail: str = "") -> None:
        self._bus.emit(ReviewProgress(stage=stage, percent=percent, detail=detail))
