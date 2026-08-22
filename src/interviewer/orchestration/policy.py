from __future__ import annotations

import logging

from ..core.config import OrchestrationSettings
from ..core.types import MAX_DEPTH, InterviewPhase, QuestionSource, TurnIntent
from ..domain.interview import InterviewState
from ..domain.question_bank import BankQuestion, DepthAction
from ..domain.turn_plan import PROBE_INTENTS, DirectorDecision, TurnPlan

logger = logging.getLogger(__name__)

_PHASE_INTENTS: dict[InterviewPhase, tuple[TurnIntent, ...]] = {
    InterviewPhase.WARMUP: (
        TurnIntent.ASK_NEW,
        TurnIntent.FOLLOW_UP,
        TurnIntent.ACKNOWLEDGE,
        TurnIntent.TRANSITION,
    ),
    InterviewPhase.RESUME_DEEP_DIVE: (
        TurnIntent.ASK_NEW,
        TurnIntent.FOLLOW_UP,
        TurnIntent.BOUNDARY_TEST,
        TurnIntent.PRESSURE,
        TurnIntent.ACKNOWLEDGE,
        TurnIntent.TRANSITION,
    ),
    InterviewPhase.TECH_DEPTH: (
        TurnIntent.ASK_NEW,
        TurnIntent.FOLLOW_UP,
        TurnIntent.BOUNDARY_TEST,
        TurnIntent.PRESSURE,
        TurnIntent.ACKNOWLEDGE,
        TurnIntent.TRANSITION,
    ),
    InterviewPhase.BEHAVIORAL: (
        TurnIntent.ASK_NEW,
        TurnIntent.FOLLOW_UP,
        TurnIntent.STAR_PROBE,
        TurnIntent.PRESSURE,
        TurnIntent.ACKNOWLEDGE,
        TurnIntent.TRANSITION,
    ),
    InterviewPhase.CODING: (
        TurnIntent.CODING_HANDOFF,
        TurnIntent.BOUNDARY_TEST,
        TurnIntent.FOLLOW_UP,
        TurnIntent.ACKNOWLEDGE,
        TurnIntent.TRANSITION,
    ),
    InterviewPhase.STRESS: (
        TurnIntent.PRESSURE,
        TurnIntent.FOLLOW_UP,
        TurnIntent.BOUNDARY_TEST,
        TurnIntent.ASK_NEW,
        TurnIntent.TRANSITION,
    ),
    InterviewPhase.CANDIDATE_QA: (
        TurnIntent.ACKNOWLEDGE,
        TurnIntent.ASK_NEW,
        TurnIntent.TRANSITION,
    ),
    InterviewPhase.CLOSING: (TurnIntent.CLOSE,),
    InterviewPhase.FINISHED: (TurnIntent.CLOSE,),
}

_PHASE_SOURCES: dict[InterviewPhase, tuple[QuestionSource, ...]] = {
    InterviewPhase.WARMUP: (QuestionSource.RESUME_PROJECT, QuestionSource.RESUME_SKILL),
    InterviewPhase.RESUME_DEEP_DIVE: (
        QuestionSource.RESUME_PROJECT,
        QuestionSource.JD_REQUIREMENT,
        QuestionSource.RESUME_SKILL,
    ),
    InterviewPhase.TECH_DEPTH: (
        QuestionSource.JD_REQUIREMENT,
        QuestionSource.FUNDAMENTAL,
        QuestionSource.RESUME_SKILL,
    ),
    InterviewPhase.BEHAVIORAL: (QuestionSource.BEHAVIORAL,),
    InterviewPhase.CODING: (QuestionSource.CODING,),
    InterviewPhase.STRESS: (
        QuestionSource.JD_REQUIREMENT,
        QuestionSource.RESUME_PROJECT,
        QuestionSource.FUNDAMENTAL,
    ),
    InterviewPhase.CANDIDATE_QA: (),
    InterviewPhase.CLOSING: (),
    InterviewPhase.FINISHED: (),
}

# 追问类 intent，受追问深度上限约束
_PROBE_INTENTS: frozenset[TurnIntent] = frozenset(
    {TurnIntent.FOLLOW_UP, TurnIntent.STAR_PROBE, TurnIntent.BOUNDARY_TEST}
)


def plan_turn(state: InterviewState, settings: OrchestrationSettings) -> TurnPlan:
    """把状态机的硬约束算出来。这里全部是确定性规则，不调模型。"""
    if state.must_close():
        return TurnPlan(
            allowed_intents=[TurnIntent.CLOSE],
            depth_action=None,
            phase_hint="时间已到收尾线，本轮必须结束面试。",
            must_close=True,
        )

    current = state.current_question
    depth_action = state.last_depth_action
    has_answer = bool(current and current.answer_text.strip())

    follow_up_allowed = has_answer and state.can_follow_up(settings.max_follow_up_depth)
    interrupt_allowed = state.can_interrupt(settings.interrupt_budget_per_phase)

    avoid: tuple[str, ...] = ()
    prefer: str | None = None
    if depth_action in (DepthAction.SWITCH, DepthAction.ABANDON):
        if state.current_domain:
            avoid = (state.current_domain,)
        follow_up_allowed = False
    elif depth_action in (DepthAction.DEEPEN, DepthAction.SIDESTEP):
        prefer = state.current_domain or None

    intents = list(_PHASE_INTENTS[state.phase])
    if state.phase is InterviewPhase.WARMUP and current is not None and has_answer:
        # 暖场首答只允许顺着候选人的自我介绍追问，不能跳到题库的预设问题。
        intents = [TurnIntent.FOLLOW_UP]

    if not follow_up_allowed:
        intents = [i for i in intents if i not in _PROBE_INTENTS]
    if depth_action is DepthAction.SIDESTEP:
        intents = [i for i in intents if i is not TurnIntent.BOUNDARY_TEST]
    if depth_action is DepthAction.ABANDON:
        intents = [i for i in intents if i not in {TurnIntent.PRESSURE, TurnIntent.BOUNDARY_TEST}]
    if state.phase is InterviewPhase.BEHAVIORAL and not state.star.missing:
        intents = [i for i in intents if i is not TurnIntent.STAR_PROBE]
    if state.persona.pressure.challenge_frequency < 4:
        intents = [i for i in intents if i is not TurnIntent.PRESSURE]
    if not has_answer:
        intents = [i for i in intents if i is not TurnIntent.ACKNOWLEDGE]

    force_personality = state.personality_probe_due() and _last_quality(state) >= 0.55
    sources = _PHASE_SOURCES[state.phase]
    if force_personality:
        sources = (QuestionSource.BEHAVIORAL,)

    candidates: list[BankQuestion] = []
    if state.phase is not InterviewPhase.CANDIDATE_QA:
        candidates = state.bank.candidates(
            asked_ids=state.asked_ids(),
            progress=state.skill_progress,
            sources=sources or None,
            prefer_domain=prefer,
            avoid_domains=avoid,
            limit=4,
        )
        if not candidates and sources:
            candidates = state.bank.candidates(
                asked_ids=state.asked_ids(),
                progress=state.skill_progress,
                sources=None,
                prefer_domain=prefer,
                avoid_domains=avoid,
                limit=4,
            )

    pending_must = state.bank.pending_must_ask(state.asked_ids())
    if pending_must and _time_pressure(state) and not force_personality:
        candidates = pending_must[:3]

    if not candidates:
        intents = [i for i in intents if i is not TurnIntent.ASK_NEW]
    if state.is_phase_over() and TurnIntent.TRANSITION not in intents:
        intents.append(TurnIntent.TRANSITION)
    if not intents:
        intents = [TurnIntent.TRANSITION]

    return TurnPlan(
        allowed_intents=intents,
        candidates=candidates,
        depth_action=depth_action,
        phase_hint=_phase_hint(state, depth_action, pending_must),
        interrupt_allowed=interrupt_allowed,
        follow_up_allowed=follow_up_allowed,
        force_personality=force_personality,
        must_close=False,
        prefer_domain=prefer,
        avoid_domains=avoid,
    )


def _last_quality(state: InterviewState) -> float:
    for question in reversed(state.questions):
        if question.quality is not None:
            return question.quality
    return 0.5


def _time_pressure(state: InterviewState) -> bool:
    """剩余时间不足总时长三成时，必问项优先。"""
    return state.remaining_ms <= state.plan.total_ms * 0.3


def _phase_hint(
    state: InterviewState, action: DepthAction | None, pending_must: list[BankQuestion]
) -> str:
    parts: list[str] = []
    if action is not None:
        parts.append(f"上一题的推进判定：{action.label}")
    if action is DepthAction.ABANDON:
        parts.append("他这块确实不会，不要再追，换个领域，这一项按低分记录。")
    elif action is DepthAction.DEEPEN:
        current = state.current_question
        depth = min(MAX_DEPTH, (current.depth if current else 1) + 1)
        parts.append(f"可以往 D{depth} 深一层。")
    elif action is DepthAction.SWITCH:
        parts.append("这个领域问够了，换一个领域。")

    if state.is_phase_over():
        parts.append(f"本阶段时间已用满，尽快切到「{state.next_phase().label}」。")
    else:
        parts.append(
            f"本阶段还剩 {max(0, state.phase_budget_ms() - state.phase_elapsed_ms) // 1000} 秒。"
        )
    if pending_must:
        parts.append("仍有 JD 必问项未覆盖：" + "、".join(q.skill for q in pending_must[:4]) + "。")
    if state.personality_probe_due():
        parts.append("现在是穿插一个性格或价值观问题的合适时机。")
    return " ".join(parts)


def enforce_depth_action(
    state: InterviewState, decision: DirectorDecision, action: DepthAction | None
) -> DirectorDecision:
    """规则是最终裁决者。导演还想在一个答不上来的点上纠缠时，这里把它拉走。"""
    if action not in (DepthAction.SWITCH, DepthAction.ABANDON):
        return decision
    if decision.intent not in PROBE_INTENTS:
        return decision

    avoid = (state.current_domain,) if state.current_domain else ()
    candidates = state.bank.candidates(
        asked_ids=state.asked_ids(),
        progress=state.skill_progress,
        sources=None,
        avoid_domains=avoid,
        limit=1,
    )
    if not candidates:
        logger.info("深度规则改判：无可用新题，转为切换环节")
        return decision.model_copy(
            update={
                "intent": TurnIntent.TRANSITION,
                "brief": f"结束当前话题，切到{state.next_phase().label}",
                "chosen_question": None,
            }
        )

    question = candidates[0]
    logger.info(
        "深度规则改判：%s -> ask_new(%s)，原因=%s",
        decision.intent.value,
        question.skill,
        action.value,
    )
    return decision.model_copy(
        update={
            "intent": TurnIntent.ASK_NEW,
            "brief": question.brief_for_director(),
            "chosen_question": question,
            "target_skill": question.skill,
            "domain": question.domain,
            "depth": question.depth,
        }
    )


def interrupt_threshold_ms(state: InterviewState, settings: OrchestrationSettings) -> int:
    """候选人啰嗦多久该被打断。人设的打断倾向越高，阈值越短。"""
    base = settings.verbose_seconds_before_interrupt
    return int(state.persona.interrupt_threshold_seconds(base) * 1000)


def resolve_phase_transition(state: InterviewState) -> InterviewPhase | None:
    """返回应当进入的下一阶段，无需切换则返回 None。"""
    if state.must_close():
        return None if state.phase is InterviewPhase.CLOSING else InterviewPhase.CLOSING
    if state.is_phase_over():
        nxt = state.next_phase()
        return nxt if nxt is not state.phase else None
    return None
