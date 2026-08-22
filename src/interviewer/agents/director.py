from __future__ import annotations

import logging
from typing import ClassVar

from pydantic import Field

from ..core.errors import ProviderResponseError
from ..core.types import ScoreDimension, TurnIntent
from ..domain.interview import InterviewState
from ..domain.question_bank import BankQuestion
from ..domain.turn_plan import (
    NEW_QUESTION_INTENTS,
    PROBE_INTENTS,
    DirectorDecision,
    TurnPlan,
)
from ..llm import prompts
from ..llm.base import system, user
from ..llm.coerce import LooseModel
from ..llm.router import ROLE_DIRECTOR
from .base import Agent, clamp, trim

logger = logging.getLogger(__name__)


class _DirectorRaw(LooseModel):
    intent: str = ""
    brief: str = ""
    target_skill: str = ""
    chosen_question_id: int | None = None
    is_personality: bool = False
    should_advance_phase: bool = False
    should_interrupt: bool = False
    answer_quality: float | None = None
    answer_summary: str = ""
    covered_skills: list[str] = Field(default_factory=list)
    dimension_deltas: dict[str, float] = Field(default_factory=dict)
    reasoning: str = ""


class Director(Agent):
    """面试的大脑。它不说话，只在 policy 划定的边界内决定下一步。"""

    role: ClassVar[str] = ROLE_DIRECTOR

    async def decide(self, state: InterviewState, plan: TurnPlan) -> DirectorDecision:
        if not plan.allowed_intents:
            raise ProviderResponseError("没有可用的 intent，状态机配置错误")

        # expected_signals 取自当前已问的这道题（关联回题库拿期望要点）。
        # 没有关联则降级：尝试 plan 候选里下一题，这道题多半就是要考的。
        current = state.current_question
        expected_signals: list[str] = []
        if current is not None and current.bank_question_id is not None:
            bank_q = state.bank.by_id(current.bank_question_id)
            if bank_q is not None:
                expected_signals = list(bank_q.expected_signals)
        if not expected_signals and plan.candidates:
            expected_signals = list(plan.candidates[0].expected_signals)

        # 历史评分：用当前技能点（追问时）或下一题技能点（换题时）
        skill_for_history = current.target_skill if current else ""
        if not skill_for_history and plan.candidates:
            skill_for_history = plan.candidates[0].skill
        skill_score_history = state.recent_skill_scores(skill_for_history, limit=3)

        raw = await self.client.structured(
            [
                system(prompts.DIRECTOR_SYSTEM),
                user(
                    prompts.director_user_prompt(
                        persona_focus=state.persona.style_block(),
                        state_digest=state.digest(),
                        context_block=state.context_block(),
                        last_answer=_last_answer(state),
                        allowed_intents=[i.value for i in plan.allowed_intents],
                        candidate_block=plan.candidate_block(),
                        phase_hint=plan.phase_hint,
                        interrupt_allowed=plan.interrupt_allowed,
                        follow_up_allowed=plan.follow_up_allowed,
                        force_personality=plan.force_personality,
                        expected_signals=expected_signals or None,
                        skill_score_history=skill_score_history or None,
                    )
                ),
            ],
            _DirectorRaw,
            temperature=0.5,
            max_tokens=1400,
        )

        intent = _resolve_intent(raw.intent, plan)
        chosen = _resolve_question(raw.chosen_question_id, intent, plan)

        if intent in NEW_QUESTION_INTENTS and chosen is None:
            if plan.follow_up_allowed and TurnIntent.FOLLOW_UP in plan.allowed_intents:
                intent = TurnIntent.FOLLOW_UP
            elif TurnIntent.TRANSITION in plan.allowed_intents:
                intent = TurnIntent.TRANSITION
            else:
                intent = plan.allowed_intents[0]

        brief = trim(raw.brief, 150)
        if chosen is not None:
            # 下发用不含 jd_ref 的版本：JD 原文写法是「熟悉 XXX」，
            # 直接给语音会被当成候选人的自述念出来
            brief = trim(chosen.brief_for_voice(), 200)
        if not brief:
            raise ProviderResponseError("导演未给出可执行的 brief")

        target_skill = trim(raw.target_skill, 60)
        domain = ""
        depth = 1
        if chosen is not None:
            target_skill = chosen.skill
            domain = chosen.domain
            depth = chosen.depth
        elif intent in PROBE_INTENTS:
            current = state.current_question
            if current is not None:
                target_skill = target_skill or current.target_skill
                domain = current.domain
                depth = min(4, current.depth + (1 if intent is TurnIntent.BOUNDARY_TEST else 0))

        decision = DirectorDecision(
            intent=intent,
            brief=brief,
            target_skill=target_skill,
            domain=domain,
            depth=depth,
            chosen_question=chosen,
            is_personality=bool(raw.is_personality or plan.force_personality),
            should_advance_phase=raw.should_advance_phase,
            should_interrupt=bool(raw.should_interrupt and plan.interrupt_allowed),
            answer_quality=None if raw.answer_quality is None else clamp(raw.answer_quality),
            answer_summary=trim(raw.answer_summary, 120),
            covered_skills=[trim(s, 40) for s in raw.covered_skills if s.strip()][:6],
            dimension_deltas=_coerce_dimensions(raw.dimension_deltas),
        )
        logger.info(
            "导演决策 intent=%s qid=%s skill=%s depth=%s advance=%s interrupt=%s",
            decision.intent.value,
            chosen.id if chosen else None,
            decision.target_skill,
            decision.depth,
            decision.should_advance_phase,
            decision.should_interrupt,
        )
        return decision


def _last_answer(state: InterviewState) -> str:
    current = state.current_question
    if current is not None and current.answer_text.strip():
        return current.answer_text.strip()
    last_turn = state.last_candidate_turn()
    return last_turn.text if last_turn else ""


def _resolve_intent(value: str, plan: TurnPlan) -> TurnIntent:
    try:
        intent = TurnIntent(value.strip().lower())
    except ValueError:
        logger.warning("导演给出未知 intent: %s", value)
        return plan.allowed_intents[0]
    if intent not in plan.allowed_intents:
        logger.warning("导演越界 intent=%s，按边界回落", intent.value)
        return plan.allowed_intents[0]
    return intent


def _resolve_question(
    question_id: int | None, intent: TurnIntent, plan: TurnPlan
) -> BankQuestion | None:
    if intent not in NEW_QUESTION_INTENTS or not plan.candidates:
        return None
    if question_id is not None:
        match = next((q for q in plan.candidates if q.id == question_id), None)
        if match is not None:
            return match
        logger.warning("导演选了不在候选集里的题目 id=%s，按优先级取第一个", question_id)
    return plan.candidates[0]


def _coerce_dimensions(raw: dict[str, float]) -> dict[ScoreDimension, float]:
    result: dict[ScoreDimension, float] = {}
    for key, value in raw.items():
        try:
            dim = ScoreDimension(key.strip().lower())
        except ValueError:
            continue
        result[dim] = clamp(float(value), 0.0, 100.0)
    return result
