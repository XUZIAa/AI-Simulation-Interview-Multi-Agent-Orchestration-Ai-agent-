from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select, update

from ...core.types import GapSeverity, ScoreDimension
from ...domain.review import MistakeItem, ReviewReport
from ..models import MistakeRow, ReviewRow, SessionRow, SkillTrendRow
from .base import Repository, chunked

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class StoredMistake:
    id: int
    session_id: int | None
    item: MistakeItem
    hit_count: int
    mastered: bool
    last_seen_at: datetime


@dataclass(slots=True)
class TrendPoint:
    session_id: int
    recorded_at: datetime
    score: float


class ReviewRepository(Repository):
    async def save_review(self, report: ReviewReport) -> None:
        """报告本体、错题、趋势点分三步写，任一步失败不影响已落地的部分。"""
        await self._save_report_body(report)
        await self._merge_mistakes(report)
        await self._save_trend(report)

    async def _save_report_body(self, report: ReviewReport) -> None:
        payload = report.model_dump(mode="json")
        async with self.db.transaction() as session:
            stmt = select(ReviewRow).where(ReviewRow.session_id == report.session_id)
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is None:
                session.add(
                    ReviewRow(
                        session_id=report.session_id,
                        overall_score=report.overall_score,
                        payload=payload,
                    )
                )
            else:
                row.overall_score = report.overall_score
                row.payload = payload
            await session.execute(
                update(SessionRow)
                .where(SessionRow.id == report.session_id)
                .values(overall_score=report.overall_score)
            )

    async def _merge_mistakes(self, report: ReviewReport) -> None:
        for batch in chunked(report.mistakes, 20):
            for item in batch:
                async with self.db.transaction() as session:
                    stmt = select(MistakeRow).where(
                        MistakeRow.knowledge_point == item.knowledge_point,
                        MistakeRow.mastered.is_(False),
                    )
                    row = (await session.execute(stmt)).scalar_one_or_none()
                    if row is None:
                        session.add(
                            MistakeRow(
                                session_id=report.session_id,
                                knowledge_point=item.knowledge_point,
                                topic=item.topic,
                                question=item.question,
                                candidate_answer=item.candidate_answer,
                                key_points=list(item.key_points),
                                severity=item.severity.value,
                                review_hint=item.review_hint,
                            )
                        )
                    else:
                        row.hit_count += 1
                        row.last_seen_at = datetime.now(UTC)
                        row.session_id = report.session_id
                        row.question = item.question or row.question
                        row.candidate_answer = item.candidate_answer or row.candidate_answer
                        row.key_points = list(item.key_points) or row.key_points
                        row.review_hint = item.review_hint or row.review_hint
                        if item.severity is GapSeverity.BLOCKER:
                            row.severity = item.severity.value

    async def _save_trend(self, report: ReviewReport) -> None:
        async with self.db.transaction() as session:
            for dim in report.dimensions:
                stmt = select(SkillTrendRow).where(
                    SkillTrendRow.session_id == report.session_id,
                    SkillTrendRow.dimension == dim.dimension.value,
                )
                row = (await session.execute(stmt)).scalar_one_or_none()
                if row is None:
                    session.add(
                        SkillTrendRow(
                            session_id=report.session_id,
                            dimension=dim.dimension.value,
                            score=dim.score,
                        )
                    )
                else:
                    row.score = dim.score

    async def get_review(self, session_id: int) -> ReviewReport | None:
        async with self.db.session() as session:
            stmt = select(ReviewRow).where(ReviewRow.session_id == session_id)
            row = (await session.execute(stmt)).scalar_one_or_none()
        return ReviewReport.model_validate(row.payload) if row else None

    async def list_mistakes(
        self, *, include_mastered: bool = False, topic: str = "", limit: int = 200
    ) -> list[StoredMistake]:
        async with self.db.session() as session:
            stmt = select(MistakeRow)
            if not include_mastered:
                stmt = stmt.where(MistakeRow.mastered.is_(False))
            if topic:
                stmt = stmt.where(MistakeRow.topic == topic)
            stmt = stmt.order_by(
                MistakeRow.mastered, MistakeRow.hit_count.desc(), MistakeRow.last_seen_at.desc()
            ).limit(limit)
            rows = (await session.execute(stmt)).scalars().all()
        return [
            StoredMistake(
                id=r.id,
                session_id=r.session_id,
                item=MistakeItem(
                    knowledge_point=r.knowledge_point,
                    topic=r.topic,
                    question=r.question,
                    candidate_answer=r.candidate_answer,
                    key_points=list(r.key_points or []),
                    severity=GapSeverity(r.severity),
                    review_hint=r.review_hint,
                ),
                hit_count=r.hit_count,
                mastered=r.mastered,
                last_seen_at=r.last_seen_at,
            )
            for r in rows
        ]

    async def topics(self) -> list[str]:
        async with self.db.session() as session:
            stmt = select(MistakeRow.topic).where(MistakeRow.topic != "").distinct()
            return sorted((await session.execute(stmt)).scalars().all())

    async def set_mastered(self, mistake_id: int, mastered: bool) -> None:
        async with self.db.transaction() as session:
            await session.execute(
                update(MistakeRow).where(MistakeRow.id == mistake_id).values(mastered=mastered)
            )

    async def delete_mistake(self, mistake_id: int) -> None:
        async with self.db.transaction() as session:
            row = await session.get(MistakeRow, mistake_id)
            if row is not None:
                await session.delete(row)

    async def mistake_counts(self) -> tuple[int, int]:
        async with self.db.session() as session:
            pending = (
                await session.execute(
                    select(func.count(MistakeRow.id)).where(MistakeRow.mastered.is_(False))
                )
            ).scalar_one()
            mastered = (
                await session.execute(
                    select(func.count(MistakeRow.id)).where(MistakeRow.mastered.is_(True))
                )
            ).scalar_one()
        return int(pending), int(mastered)

    async def dimension_series(self, limit: int = 20) -> dict[ScoreDimension, list[TrendPoint]]:
        async with self.db.session() as session:
            stmt = (
                select(SkillTrendRow)
                .order_by(SkillTrendRow.recorded_at.desc())
                .limit(limit * len(ScoreDimension))
            )
            rows = (await session.execute(stmt)).scalars().all()
        series: dict[ScoreDimension, list[TrendPoint]] = {}
        for row in reversed(rows):
            try:
                dim = ScoreDimension(row.dimension)
            except ValueError:
                continue
            series.setdefault(dim, []).append(
                TrendPoint(session_id=row.session_id, recorded_at=row.recorded_at, score=row.score)
            )
        return series

    async def overall_series(self, limit: int = 20) -> list[TrendPoint]:
        async with self.db.session() as session:
            stmt = (
                select(ReviewRow)
                .order_by(ReviewRow.created_at.desc())
                .limit(limit)
            )
            rows = (await session.execute(stmt)).scalars().all()
        return [
            TrendPoint(session_id=r.session_id, recorded_at=r.created_at, score=r.overall_score)
            for r in reversed(rows)
        ]
