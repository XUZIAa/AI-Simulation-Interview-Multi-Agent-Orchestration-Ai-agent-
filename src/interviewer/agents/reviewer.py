from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import ClassVar

from pydantic import AliasChoices, Field

from ..core.types import AnnotationKind, CompanyTier, GapSeverity, ScoreDimension
from ..domain.company import score_weights
from ..domain.interview import InterviewState
from ..domain.review import (
    AbandonedSkill,
    AnswerRewrite,
    DimensionScore,
    DrillItem,
    ImprovementPlan,
    MistakeItem,
    ProsodyReport,
    ReviewReport,
    TranscriptAnnotation,
)
from ..llm import prompts
from ..llm.base import system, user
from ..llm.coerce import LooseModel
from ..llm.router import ROLE_ANALYST
from .base import Agent, clamp, trim

logger = logging.getLogger(__name__)

ProgressHook = Callable[[str, int, str], None]


class _DimRaw(LooseModel):
    dimension: str = Field(default="", validation_alias=AliasChoices("dimension", "name"))
    score: float = 0.0
    reason: str = ""
    evidence: list[str] = Field(default_factory=list)


class _ScoreRaw(LooseModel):
    overall_score: float = 0.0
    headline: str = ""
    summary: str = ""
    dimensions: list[_DimRaw] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    improvements: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)


class _AnnotationRaw(LooseModel):
    turn_index: int = 0
    kind: str = "weakness"
    quote: str = Field(default="", validation_alias=AliasChoices("quote", "name", "text"))
    comment: str = ""


class _AnnotationsRaw(LooseModel):
    annotations: list[_AnnotationRaw] = Field(default_factory=list)


class _RewriteRaw(LooseModel):
    question_index: int = 0
    question: str = Field(default="", validation_alias=AliasChoices("question", "name"))
    original: str = ""
    rewritten: str = ""
    why_better: list[str] = Field(default_factory=list)
    used_assets: list[str] = Field(default_factory=list)


class _RewritesRaw(LooseModel):
    rewrites: list[_RewriteRaw] = Field(default_factory=list)


class _MistakeRaw(LooseModel):
    knowledge_point: str = Field(
        default="", validation_alias=AliasChoices("knowledge_point", "name", "point")
    )
    topic: str = ""
    question: str = ""
    candidate_answer: str = ""
    key_points: list[str] = Field(default_factory=list)
    severity: str = "major"
    review_hint: str = ""


class _MistakesRaw(LooseModel):
    mistakes: list[_MistakeRaw] = Field(default_factory=list)


class _DrillRaw(LooseModel):
    action: str = Field(default="", validation_alias=AliasChoices("action", "name", "task"))
    why: str = ""
    time_cost: str = ""


class _PlanRaw(LooseModel):
    focus_area: str = Field(default="", validation_alias=AliasChoices("focus_area", "name", "area", "focus"))
    diagnosis: str = ""
    expected_gain: str = ""
    drills: list[_DrillRaw] = Field(default_factory=list)
    resources: list[str] = Field(default_factory=list)
    next_mock_setup: str = ""


class _PlansRaw(LooseModel):
    plans: list[_PlanRaw] = Field(default_factory=list)


class Reviewer(Agent):
    """面试后的离线复盘。四个子任务并发跑，任一失败不拖垮其余。"""

    role: ClassVar[str] = ROLE_ANALYST

    async def compose(
        self,
        state: InterviewState,
        *,
        transcript: str,
        question_digest: str,
        coding_summary: str,
        prosody: ProsodyReport,
        prosody_summary: str,
        on_progress: ProgressHook | None = None,
    ) -> ReviewReport:
        base_context = prompts.review_user_prompt(
            persona_name=f"{state.persona.name}（{state.persona.display_archetype}）",
            jd_digest=state.jd_digest,
            resume_digest=state.resume_digest,
            transcript=transcript,
            coding_summary=coding_summary,
            prosody_summary=prosody_summary,
        )
        has_coding = bool(coding_summary.strip())

        def progress(stage: str, percent: int, detail: str = "") -> None:
            if on_progress:
                on_progress(stage, percent, detail)

        progress("scoring", 10, "正在给多维能力打分")
        results = await asyncio.gather(
            self._score(base_context, has_coding=has_coding),
            self._annotate(base_context),
            self._rewrite(base_context, question_digest),
            self._mistakes(base_context, question_digest),
            return_exceptions=True,
        )
        progress("assembling", 85, "正在汇总报告")

        score_raw = _unwrap(results[0], _ScoreRaw())
        annotations_raw = _unwrap(results[1], _AnnotationsRaw())
        rewrites_raw = _unwrap(results[2], _RewritesRaw())
        mistakes_raw = _unwrap(results[3], _MistakesRaw())

        dimensions = _build_dimensions(score_raw.dimensions, has_coding=has_coding)
        # 总分以确定性加权为准，模型的整体判断只在维度缺失时兜底
        overall = (
            weighted_overall(dimensions, state.company_tier)
            if dimensions
            else clamp(score_raw.overall_score, 0.0, 100.0)
        )

        abandoned = [
            AbandonedSkill(
                skill=p.skill,
                domain=p.domain,
                abandoned_at_depth=p.abandoned_at_depth,
                attempts=p.attempts,
            )
            for p in state.exhausted_skills()
        ]
        mistakes = _build_mistakes(mistakes_raw.mistakes)

        report = ReviewReport(
            session_id=state.session_id,
            duration_ms=state.elapsed_ms,
            reviewable=state.reviewable,
            overall_score=overall,
            headline=trim(score_raw.headline, 120),
            summary=score_raw.summary.strip()[:1200],
            dimensions=dimensions,
            annotations=_build_annotations(annotations_raw.annotations, valid_turns=len(state.turns)),
            rewrites=_build_rewrites(rewrites_raw.rewrites),
            mistakes=mistakes,
            prosody=prosody,
            strengths=[trim(s, 60) for s in score_raw.strengths if s.strip()][:5],
            improvements=[trim(s, 60) for s in score_raw.improvements if s.strip()][:5],
            next_actions=[trim(s, 80) for s in score_raw.next_actions if s.strip()][:5],
            abandoned_skills=abandoned,
        )

        progress("improvement", 92, "正在生成专项提升方案")
        report.improvement_plans = await self._improvement(
            report, abandoned=abandoned, jd_digest=state.jd_digest
        )
        progress("done", 100, "复盘完成")
        return report

    async def _improvement(
        self, report: ReviewReport, *, abandoned: list[AbandonedSkill], jd_digest: str
    ) -> list[ImprovementPlan]:
        dimension_lines = "\n".join(
            f"- {d.dimension.label}：{d.score:.0f} 分。{d.reason}" for d in report.dimensions
        )
        abandoned_lines = "\n".join(
            f"- {a.skill}（{a.domain}）：问到 D{a.abandoned_at_depth} 就答不上来，共尝试 {a.attempts} 次"
            for a in abandoned
        )
        mistake_lines = "\n".join(
            f"- {m.knowledge_point}（{m.topic}）：{m.candidate_answer}" for m in report.mistakes[:8]
        )
        try:
            raw = await self.client.structured(
                [
                    system(prompts.IMPROVEMENT_SYSTEM),
                    user(
                        prompts.improvement_user_prompt(
                            headline=report.headline,
                            dimension_lines=dimension_lines or "（无维度数据）",
                            abandoned_lines=abandoned_lines,
                            mistake_lines=mistake_lines,
                            jd_digest=jd_digest,
                        )
                    ),
                ],
                _PlansRaw,
                temperature=0.4,
                max_tokens=3500,
            )
        except Exception:
            logger.exception("专项提升方案生成失败")
            return []
        return _build_plans(raw.plans)

    async def _score(self, context: str, *, has_coding: bool) -> _ScoreRaw:
        note = "" if has_coding else "\n\n注意：本场没有编码环节，结果里不要出现 coding 维度。"
        return await self.client.structured(
            [system(prompts.REVIEW_SCORE_SYSTEM), user(context + note)],
            _ScoreRaw,
            temperature=0.3,
            max_tokens=4000,
        )

    async def _annotate(self, context: str) -> _AnnotationsRaw:
        return await self.client.structured(
            [system(prompts.ANNOTATE_SYSTEM), user(context)],
            _AnnotationsRaw,
            temperature=0.3,
            max_tokens=4000,
        )

    async def _rewrite(self, context: str, question_digest: str) -> _RewritesRaw:
        return await self.client.structured(
            [
                system(prompts.REWRITE_SYSTEM),
                user(f"{context}\n\n【按题号整理的问答】\n{question_digest}"),
            ],
            _RewritesRaw,
            temperature=0.5,
            max_tokens=5000,
        )

    async def _mistakes(self, context: str, question_digest: str) -> _MistakesRaw:
        return await self.client.structured(
            [
                system(prompts.MISTAKES_SYSTEM),
                user(f"{context}\n\n【按题号整理的问答】\n{question_digest}"),
            ],
            _MistakesRaw,
            temperature=0.2,
            max_tokens=3500,
        )


def _unwrap[T](result: T | BaseException, fallback: T) -> T:
    if isinstance(result, BaseException):
        logger.error("复盘子任务失败: %s", result)
        return fallback
    return result


_DIMENSION_WEIGHT: dict[ScoreDimension, float] = {
    ScoreDimension.TECH_DEPTH: 0.32,
    ScoreDimension.EXPRESSION: 0.2,
    ScoreDimension.RESILIENCE: 0.14,
    ScoreDimension.VALUE_FIT: 0.12,
    ScoreDimension.CODING: 0.14,
    ScoreDimension.COLLABORATION: 0.08,
}


def _build_dimensions(raw: list[_DimRaw], *, has_coding: bool) -> list[DimensionScore]:
    seen: set[ScoreDimension] = set()
    result: list[DimensionScore] = []
    for item in raw:
        try:
            dim = ScoreDimension(item.dimension.strip().lower())
        except ValueError:
            continue
        if dim in seen:
            continue
        if dim is ScoreDimension.CODING and not has_coding:
            continue
        seen.add(dim)
        result.append(
            DimensionScore(
                dimension=dim,
                score=clamp(item.score, 0.0, 100.0),
                reason=trim(item.reason, 160),
                evidence=[trim(e, 120) for e in item.evidence if e.strip()][:3],
            )
        )
    order = list(_DIMENSION_WEIGHT)
    result.sort(key=lambda d: order.index(d.dimension))
    return result


def weighted_overall(dimensions: list[DimensionScore], tier: CompanyTier) -> float:
    """按公司类型的评分口径加权。同样的表现，大厂看深度、制造业看稳定。"""
    weights = score_weights(tier)
    total_weight = sum(weights[d.dimension] for d in dimensions)
    if total_weight <= 0:
        return 0.0
    weighted = sum(d.score * weights[d.dimension] for d in dimensions)
    return round(weighted / total_weight, 1)


def _build_plans(raw: list[_PlanRaw]) -> list[ImprovementPlan]:
    plans: list[ImprovementPlan] = []
    for item in raw:
        focus = trim(item.focus_area, 40)
        if not focus:
            continue
        drills = [
            DrillItem(
                action=trim(d.action, 120),
                why=trim(d.why, 80),
                time_cost=trim(d.time_cost, 20),
            )
            for d in item.drills
            if d.action.strip()
        ][:5]
        if not drills:
            continue
        plans.append(
            ImprovementPlan(
                focus_area=focus,
                diagnosis=trim(item.diagnosis, 160),
                expected_gain=trim(item.expected_gain, 80),
                drills=drills,
                resources=[trim(r, 60) for r in item.resources if r.strip()][:4],
                next_mock_setup=trim(item.next_mock_setup, 160),
            )
        )
    return plans[:3]


def _build_annotations(raw: list[_AnnotationRaw], *, valid_turns: int) -> list[TranscriptAnnotation]:
    result: list[TranscriptAnnotation] = []
    for item in raw:
        if not 1 <= item.turn_index <= max(1, valid_turns):
            continue
        try:
            kind = AnnotationKind(item.kind.strip().lower())
        except ValueError:
            continue
        comment = trim(item.comment, 120)
        if not comment:
            continue
        result.append(
            TranscriptAnnotation(
                turn_index=item.turn_index,
                kind=kind,
                quote=trim(item.quote, 60),
                comment=comment,
            )
        )
    return result[:24]


def _build_rewrites(raw: list[_RewriteRaw]) -> list[AnswerRewrite]:
    result: list[AnswerRewrite] = []
    for item in raw:
        rewritten = item.rewritten.strip()
        if len(rewritten) < 40:
            continue
        result.append(
            AnswerRewrite(
                question_index=max(0, item.question_index),
                question=trim(item.question, 160),
                original=item.original.strip()[:800],
                rewritten=rewritten[:1500],
                why_better=[trim(w, 50) for w in item.why_better if w.strip()][:4],
                used_assets=[trim(a, 40) for a in item.used_assets if a.strip()][:6],
            )
        )
    return result[:5]


def _build_mistakes(raw: list[_MistakeRaw]) -> list[MistakeItem]:
    result: list[MistakeItem] = []
    seen: set[str] = set()
    for item in raw:
        point = trim(item.knowledge_point, 40)
        key = point.lower()
        if not point or key in seen:
            continue
        seen.add(key)
        try:
            severity = GapSeverity(item.severity.strip().lower())
        except ValueError:
            severity = GapSeverity.MAJOR
        result.append(
            MistakeItem(
                knowledge_point=point,
                topic=trim(item.topic, 20),
                question=trim(item.question, 160),
                candidate_answer=trim(item.candidate_answer, 80),
                key_points=[trim(p, 40) for p in item.key_points if p.strip()][:5],
                severity=severity,
                review_hint=trim(item.review_hint, 100),
            )
        )
    order = {GapSeverity.BLOCKER: 0, GapSeverity.MAJOR: 1, GapSeverity.MINOR: 2}
    result.sort(key=lambda m: order[m.severity])
    return result[:12]
