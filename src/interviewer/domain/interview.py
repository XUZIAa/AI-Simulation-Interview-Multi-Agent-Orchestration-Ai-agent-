from __future__ import annotations

from pydantic import BaseModel, Field

from ..core.types import (
    MAX_DEPTH,
    PHASE_ORDER,
    CompanyTier,
    DriftKind,
    InterviewPhase,
    JobLevel,
    ScoreDimension,
    Speaker,
    StarElement,
    TurnIntent,
)
from .company import company_profile
from .persona import PersonaContract
from .question_bank import DepthAction, QuestionBank, SkillProgress, progress_for
from .resume import GapReport

# 时长档位。用户只能选档，不能在面试中自行延长
DURATION_CHOICES: tuple[int, ...] = (10, 20, 30, 45)

# 低于这个时长不足以支撑完整复盘
MIN_REVIEWABLE_MS = 5 * 60 * 1000

# 收尾至少留出的时间，到点必须交还话语权
MIN_CLOSING_MS = 35_000

# 每问几个技术题后允许穿插一次性格题
PERSONALITY_GAP = 4


class TurnRecord(BaseModel):
    index: int
    speaker: Speaker
    text: str
    started_at_ms: int
    duration_ms: int = 0
    intent: TurnIntent | None = None
    was_interrupted: bool = False
    question_index: int | None = None


class QuestionRecord(BaseModel):
    index: int
    phase: InterviewPhase
    intent: TurnIntent
    brief: str
    target_skill: str = ""
    domain: str = ""
    depth: int = 1
    bank_question_id: int | None = None
    spoken_text: str = ""
    asked_at_ms: int = 0
    follow_up_depth: int = 0
    answer_text: str = ""
    quality: float | None = None
    depth_action: DepthAction | None = None

    def short(self) -> str:
        text = self.spoken_text or self.brief
        return text[:70].replace("\n", " ")


class StarState(BaseModel):
    is_behavioral: bool = False
    present: list[StarElement] = Field(default_factory=list)
    probes_used: int = 0

    @property
    def missing(self) -> list[StarElement]:
        return [e for e in StarElement if e not in self.present]

    def reset(self, *, behavioral: bool) -> None:
        self.is_behavioral = behavioral
        self.present = []
        self.probes_used = 0

    def describe(self) -> str:
        if not self.is_behavioral:
            return ""
        got = "、".join(e.label for e in self.present) or "无"
        lack = "、".join(e.label for e in self.missing) or "无"
        return f"已覆盖：{got}；仍缺：{lack}"


class PhaseSlot(BaseModel):
    phase: InterviewPhase
    budget_ms: int
    min_questions: int = 1


class InterviewPlan(BaseModel):
    """面试开始前一次性排定，运行期只读。总时长是硬上限。"""

    total_ms: int
    slots: list[PhaseSlot]

    def slot_of(self, phase: InterviewPhase) -> PhaseSlot | None:
        return next((s for s in self.slots if s.phase is phase), None)

    def phases(self) -> list[InterviewPhase]:
        return [s.phase for s in self.slots]

    def closing_ms(self) -> int:
        slot = self.slot_of(InterviewPhase.CLOSING)
        return max(MIN_CLOSING_MS, slot.budget_ms if slot else 0)


def _phase_set(minutes: int, *, coding_enabled: bool) -> set[InterviewPhase]:
    """短面试必须砍环节，否则每个环节都走不完。"""
    phases = {
        InterviewPhase.WARMUP,
        InterviewPhase.RESUME_DEEP_DIVE,
        InterviewPhase.TECH_DEPTH,
        InterviewPhase.CLOSING,
    }
    if minutes >= 20:
        phases.add(InterviewPhase.BEHAVIORAL)
    if minutes >= 25:
        phases.add(InterviewPhase.CANDIDATE_QA)
    if minutes >= 35:
        phases.add(InterviewPhase.STRESS)
    if coding_enabled and minutes >= 20:
        phases.add(InterviewPhase.CODING)
    return phases


_FIXED_SHARE: dict[InterviewPhase, float] = {
    InterviewPhase.WARMUP: 0.09,
    InterviewPhase.CANDIDATE_QA: 0.08,
    InterviewPhase.CLOSING: 0.06,
}


def build_plan(
    persona: PersonaContract,
    planned_minutes: int,
    *,
    coding_enabled: bool,
    gap: GapReport | None = None,
) -> InterviewPlan:
    total_ms = planned_minutes * 60_000
    allowed = _phase_set(planned_minutes, coding_enabled=coding_enabled)
    probing = persona.probing
    pressure = persona.pressure
    company = company_profile(persona.company_tier)

    dynamic: dict[InterviewPhase, float] = {
        InterviewPhase.RESUME_DEEP_DIVE: probing.project_focus + company.project * 0.5,
        InterviewPhase.TECH_DEPTH: (
            (probing.fundamentals_focus + probing.system_design_focus) / 2
            + (company.fundamentals + company.system_design) * 0.25
        ),
        InterviewPhase.BEHAVIORAL: probing.behavioral_focus + company.process * 0.3,
        InterviewPhase.STRESS: (pressure.aggression + pressure.challenge_frequency) / 4,
        InterviewPhase.CODING: max(probing.coding_focus, 4) + company.algorithm * 0.3,
    }
    if gap:
        for phase, weight in gap.phase_emphasis.items():
            if phase in dynamic:
                dynamic[phase] += weight

    dynamic = {p: w for p, w in dynamic.items() if p in allowed and w > 0.4}
    if not dynamic:
        dynamic = {InterviewPhase.TECH_DEPTH: 1.0}

    fixed_ms = {p: int(total_ms * s) for p, s in _FIXED_SHARE.items() if p in allowed}
    fixed_ms[InterviewPhase.CLOSING] = max(
        MIN_CLOSING_MS, fixed_ms.get(InterviewPhase.CLOSING, MIN_CLOSING_MS)
    )
    remaining = max(60_000, total_ms - sum(fixed_ms.values()))
    weight_sum = sum(dynamic.values())

    slots: list[PhaseSlot] = []
    for phase in PHASE_ORDER:
        if phase not in allowed:
            continue
        if phase in fixed_ms:
            slots.append(PhaseSlot(phase=phase, budget_ms=fixed_ms[phase], min_questions=1))
        elif phase in dynamic:
            budget = int(remaining * dynamic[phase] / weight_sum)
            slots.append(
                PhaseSlot(phase=phase, budget_ms=budget, min_questions=max(1, budget // 200_000 + 1))
            )
    return InterviewPlan(total_ms=total_ms, slots=slots)


class InterviewState(BaseModel):
    """权威状态。实时模型的记忆不可信，一切以此为准，且每轮落盘。"""

    session_id: int
    persona: PersonaContract
    plan: InterviewPlan
    bank: QuestionBank = Field(default_factory=QuestionBank)
    company_tier: CompanyTier = CompanyTier.MID_TECH
    job_level: JobLevel = JobLevel.MID
    job_title: str = ""
    resume_digest: str = ""
    jd_digest: str = ""
    gap_digest: str = ""

    phase: InterviewPhase = InterviewPhase.WARMUP
    phase_started_at_ms: int = 0
    elapsed_ms: int = 0

    turn_index: int = 0
    question_index: int = 0
    turns: list[TurnRecord] = Field(default_factory=list)
    questions: list[QuestionRecord] = Field(default_factory=list)
    current_question_index: int | None = None

    follow_up_depth: int = 0
    pending_skills: list[str] = Field(default_factory=list)
    covered_skills: list[str] = Field(default_factory=list)

    asked_bank_ids: list[int] = Field(default_factory=list)
    skill_progress: dict[str, SkillProgress] = Field(default_factory=dict)
    domains_visited: list[str] = Field(default_factory=list)
    current_domain: str = ""
    last_depth_action: DepthAction | None = None
    questions_since_personality: int = PERSONALITY_GAP
    personality_probes_used: int = 0

    interrupts_used_in_phase: int = 0
    drift_count: int = 0
    last_drift: DriftKind = DriftKind.NONE
    turns_since_reanchor: int = 0

    star: StarState = Field(default_factory=StarState)
    live_scores: dict[ScoreDimension, float] = Field(default_factory=dict)
    coding_active: bool = False
    code_language: str = "python"
    code_snapshot: str = ""

    # ---------- 查询 ----------

    @property
    def current_question(self) -> QuestionRecord | None:
        if self.current_question_index is None:
            return None
        return next((q for q in self.questions if q.index == self.current_question_index), None)

    @property
    def phase_elapsed_ms(self) -> int:
        return max(0, self.elapsed_ms - self.phase_started_at_ms)

    @property
    def remaining_ms(self) -> int:
        return max(0, self.plan.total_ms - self.elapsed_ms)

    @property
    def reviewable(self) -> bool:
        return self.elapsed_ms >= MIN_REVIEWABLE_MS

    def phase_budget_ms(self) -> int:
        slot = self.plan.slot_of(self.phase)
        return slot.budget_ms if slot else 0

    def questions_in_phase(self) -> list[QuestionRecord]:
        return [q for q in self.questions if q.phase is self.phase]

    def last_candidate_turn(self) -> TurnRecord | None:
        return next((t for t in reversed(self.turns) if t.speaker is Speaker.CANDIDATE), None)

    def recent_dialogue(self, limit: int = 8) -> list[TurnRecord]:
        return self.turns[-limit:]

    def asked_ids(self) -> set[int]:
        return set(self.asked_bank_ids)

    def can_interrupt(self, budget_per_phase: int) -> bool:
        if self.persona.pressure.interrupt_tendency <= 1:
            return False
        return self.interrupts_used_in_phase < budget_per_phase

    def can_follow_up(self, max_depth: int) -> bool:
        ceiling = min(max_depth, max(1, self.persona.probing.follow_up_depth // 2 + 1))
        return self.follow_up_depth < ceiling

    def must_close(self) -> bool:
        """硬闸门。到点就收尾，不给模型任何自由裁量。"""
        if self.phase in (InterviewPhase.CLOSING, InterviewPhase.FINISHED):
            return True
        return self.remaining_ms <= self.plan.closing_ms()

    def is_phase_over(self) -> bool:
        slot = self.plan.slot_of(self.phase)
        if slot is None:
            return True
        asked_enough = len(self.questions_in_phase()) >= slot.min_questions
        return self.phase_elapsed_ms >= slot.budget_ms and asked_enough

    def next_phase(self) -> InterviewPhase:
        phases = self.plan.phases()
        if self.phase not in phases:
            return InterviewPhase.CLOSING
        idx = phases.index(self.phase)
        if idx + 1 < len(phases):
            return phases[idx + 1]
        return InterviewPhase.FINISHED

    def personality_probe_due(self) -> bool:
        """只在技术题问够间隔、且不在编码或收尾时才允许穿插性格题。"""
        if self.phase in (InterviewPhase.CODING, InterviewPhase.CLOSING, InterviewPhase.FINISHED):
            return False
        if self.phase is InterviewPhase.BEHAVIORAL:
            return False
        if self.persona.probing.behavioral_focus < 3:
            return False
        return self.questions_since_personality >= PERSONALITY_GAP

    def progress_of(self, skill: str) -> SkillProgress | None:
        return self.skill_progress.get(skill.strip().lower())

    def exhausted_skills(self) -> list[SkillProgress]:
        return [p for p in self.skill_progress.values() if p.exhausted]

    # ---------- 变更 ----------

    def enter_phase(self, phase: InterviewPhase) -> None:
        self.phase = phase
        self.phase_started_at_ms = self.elapsed_ms
        self.interrupts_used_in_phase = 0
        self.follow_up_depth = 0
        self.star.reset(behavioral=phase is InterviewPhase.BEHAVIORAL)
        self.coding_active = phase is InterviewPhase.CODING

    def open_question(
        self,
        *,
        intent: TurnIntent,
        brief: str,
        target_skill: str,
        domain: str = "",
        depth: int = 1,
        bank_question_id: int | None = None,
        is_personality: bool = False,
    ) -> QuestionRecord:
        self.question_index += 1
        if intent in (TurnIntent.FOLLOW_UP, TurnIntent.STAR_PROBE, TurnIntent.BOUNDARY_TEST):
            self.follow_up_depth += 1
        else:
            self.follow_up_depth = 0

        record = QuestionRecord(
            index=self.question_index,
            phase=self.phase,
            intent=intent,
            brief=brief,
            target_skill=target_skill,
            domain=domain or self.current_domain,
            depth=max(1, min(MAX_DEPTH, depth)),
            bank_question_id=bank_question_id,
            asked_at_ms=self.elapsed_ms,
            follow_up_depth=self.follow_up_depth,
        )
        self.questions.append(record)
        self.current_question_index = record.index

        if bank_question_id is not None and bank_question_id not in self.asked_bank_ids:
            self.asked_bank_ids.append(bank_question_id)
        if target_skill:
            progress_for(self.skill_progress, skill=target_skill, domain=record.domain)
            self.mark_skill_touched(target_skill)
        if record.domain:
            self.current_domain = record.domain
            if record.domain not in self.domains_visited:
                self.domains_visited.append(record.domain)

        if is_personality:
            self.questions_since_personality = 0
            self.personality_probes_used += 1
        elif intent in (TurnIntent.ASK_NEW, TurnIntent.CODING_HANDOFF):
            self.questions_since_personality += 1
        return record

    def observe_answer(self, quality: float | None) -> DepthAction | None:
        """把回答质量落到技能推进上，返回确定性的下一步动作。"""
        question = self.current_question
        if question is None or not question.target_skill:
            return None
        question.quality = quality
        state = progress_for(
            self.skill_progress, skill=question.target_skill, domain=question.domain
        )
        action = state.observe(quality)
        question.depth_action = action
        self.last_depth_action = action
        return action

    def append_turn(
        self,
        *,
        speaker: Speaker,
        text: str,
        started_at_ms: int,
        duration_ms: int,
        intent: TurnIntent | None = None,
        was_interrupted: bool = False,
    ) -> TurnRecord:
        self.turn_index += 1
        turn = TurnRecord(
            index=self.turn_index,
            speaker=speaker,
            text=text,
            started_at_ms=started_at_ms,
            duration_ms=duration_ms,
            intent=intent,
            was_interrupted=was_interrupted,
            question_index=self.current_question_index,
        )
        self.turns.append(turn)
        self.turns_since_reanchor += 1
        question = self.current_question
        if question is not None:
            if speaker is Speaker.INTERVIEWER and not question.spoken_text:
                question.spoken_text = text
            elif speaker is Speaker.CANDIDATE:
                question.answer_text = (question.answer_text + " " + text).strip()
        return turn

    def mark_skill_touched(self, skill: str) -> None:
        normalized = skill.strip()
        if not normalized:
            return
        self.pending_skills = [s for s in self.pending_skills if s.lower() != normalized.lower()]
        if all(s.lower() != normalized.lower() for s in self.covered_skills):
            self.covered_skills.append(normalized)

    def register_drift(self, kind: DriftKind) -> None:
        self.drift_count += 1
        self.last_drift = kind

    def note_reanchor(self) -> None:
        self.turns_since_reanchor = 0
        self.last_drift = DriftKind.NONE

    def needs_reanchor(self, every_turns: int) -> bool:
        return self.turns_since_reanchor >= every_turns or self.last_drift is not DriftKind.NONE

    def blend_scores(self, partial: dict[ScoreDimension, float], weight: float = 0.35) -> None:
        for dim, value in partial.items():
            current = self.live_scores.get(dim)
            self.live_scores[dim] = value if current is None else current * (1 - weight) + value * weight

    # ---------- 注入模型的状态摘要 ----------

    def digest(self) -> str:
        lines = [
            "【当前进度】",
            f"- 第 {self.turn_index} 轮对话｜阶段：{self.phase.label}"
            f"（本阶段已用 {_mmss(self.phase_elapsed_ms)} / 预算 {_mmss(self.phase_budget_ms())}）",
            f"- 整场已用 {_mmss(self.elapsed_ms)}，剩余约 {_mmss(self.remaining_ms)}"
            f"（总时长 {self.plan.total_ms // 60000} 分钟，到点必须收尾）",
        ]

        asked = self.questions[-8:]
        if asked:
            lines.append("【你已经问过的问题｜严禁重复】")
            lines += [f"{q.index}. [{q.phase.label} D{q.depth}] {q.short()}" for q in asked]

        active = [p for p in self.skill_progress.values() if p.attempts > 0 and not p.exhausted]
        if active:
            lines.append("【技能点推进状态】")
            lines += [f"- {p.summary()}" for p in active[-6:]]

        dropped = self.exhausted_skills()
        if dropped:
            lines.append(
                "【已放弃深挖｜不要再问这些，他确实不会】"
                + "、".join(f"{p.skill}(D{p.abandoned_at_depth})" for p in dropped[:6])
            )

        if self.pending_skills:
            lines.append("【必须考到但还没考的技能点】" + "、".join(self.pending_skills[:8]))
        if self.domains_visited:
            lines.append("【已覆盖领域】" + "、".join(self.domains_visited[-8:]))

        star_desc = self.star.describe()
        if star_desc:
            lines.append("【当前行为题 STAR 完整度】" + star_desc)

        if self.coding_active:
            lines.append("【编码环节进行中】围绕他屏幕上的代码提问，不要给出实现。")

        lines.append(
            f"【打断额度】本阶段已打断 {self.interrupts_used_in_phase} 次"
            f"｜追问深度 {self.follow_up_depth}｜性格题已穿插 {self.personality_probes_used} 次"
        )
        if self.must_close():
            lines.append("【硬性要求】时间已到收尾线，本轮必须结束面试，不得再提新问题。")
        return "\n".join(lines)

    def context_block(self) -> str:
        parts: list[str] = []
        header = []
        if self.job_title:
            header.append(f"目标岗位：{self.job_title}")
        header.append(f"公司类型：{self.company_tier.label}")
        header.append(f"目标级别：{self.job_level.label}")
        parts.append("【本场设定】" + "｜".join(header))
        if self.resume_digest:
            parts.append("【候选人简历要点】\n" + self.resume_digest)
        if self.jd_digest:
            parts.append("【目标岗位要求】\n" + self.jd_digest)
        if self.gap_digest:
            parts.append("【面试前诊断结论｜你要重点验证这些疑点】\n" + self.gap_digest)
        return "\n\n".join(parts)


def _mmss(ms: int) -> str:
    total = max(0, ms) // 1000
    return f"{total // 60:02d}:{total % 60:02d}"
