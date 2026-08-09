from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from ..core.types import MAX_DEPTH, QuestionSource

_SOURCE_PRIORITY: dict[QuestionSource, int] = {
    QuestionSource.JD_REQUIREMENT: 0,
    QuestionSource.RESUME_PROJECT: 1,
    QuestionSource.RESUME_SKILL: 2,
    QuestionSource.CODING: 3,
    QuestionSource.FUNDAMENTAL: 4,
    QuestionSource.BEHAVIORAL: 5,
}

GOOD_ANSWER = 0.65
WEAK_ANSWER = 0.4
ABANDON_STREAK = 2


class DepthAction(StrEnum):
    """答完一题后的确定性推进动作。模型只提供质量分，动作由规则算。"""

    DEEPEN = "deepen"
    SIDESTEP = "sidestep"
    SWITCH = "switch"
    ABANDON = "abandon"

    @property
    def label(self) -> str:
        return _ACTION_LABELS[self]


_ACTION_LABELS: dict[DepthAction, str] = {
    DepthAction.DEEPEN: "答得住，往下深一层",
    DepthAction.SIDESTEP: "答得一般，同层换角度再确认",
    DepthAction.SWITCH: "这块问够了，换领域",
    DepthAction.ABANDON: "明显答不上来，停止深挖并记低分",
}


class BankQuestion(BaseModel):
    """题库里的一道题。面试中问出的每个新问题都必须来自这里。"""

    id: int
    text: str
    skill: str
    domain: str
    depth: int = Field(default=1, ge=1, le=MAX_DEPTH)
    source: QuestionSource = QuestionSource.FUNDAMENTAL
    project_ref: str = ""
    jd_ref: str = ""
    follow_ups: list[str] = Field(default_factory=list)
    expected_signals: list[str] = Field(default_factory=list)
    must_ask: bool = False

    def brief_for_director(self) -> str:
        """给导演选题时看的，带上关联出处便于判断该不该问这道。

        不要直接下发给语音：jd_ref 存的是 JD 原文，写法通常是「熟悉 XXX」，
        面试官会把它当成候选人的自述念出来。
        """
        parts = [self.text]
        if self.project_ref:
            parts.append(f"（关联他简历里的「{self.project_ref}」）")
        if self.jd_ref:
            parts.append(f"（对应 JD 要求：{self.jd_ref}）")
        return "".join(parts)

    def brief_for_voice(self) -> str:
        """下发给语音的版本。只留题面，附带能安全说出口的项目名。"""
        if self.project_ref:
            return f"{self.text}（这道题针对他简历里的「{self.project_ref}」，可以点名这个项目）"
        return self.text

    def one_line(self) -> str:
        return f"[{self.id}] D{self.depth} {self.domain}/{self.skill}｜{self.text[:60]}"


class SkillProgress(BaseModel):
    """单个技能点的推进状态。这是「越来越深还是换领域」的唯一依据。"""

    skill: str
    domain: str
    depth_reached: int = 0
    attempts: int = 0
    attempts_at_depth: int = 0
    low_streak: int = 0
    best_quality: float = 0.0
    exhausted: bool = False
    abandoned_at_depth: int = 0

    @property
    def next_depth(self) -> int:
        return min(MAX_DEPTH, self.depth_reached + 1)

    def observe(self, quality: float | None) -> DepthAction:
        """记录一次回答并决定下一步。质量未知时按一般水平处理。"""
        self.attempts += 1
        self.attempts_at_depth += 1
        score = 0.5 if quality is None else quality
        self.best_quality = max(self.best_quality, score)

        if score >= GOOD_ANSWER:
            self.low_streak = 0
            if self.depth_reached >= MAX_DEPTH:
                return DepthAction.SWITCH
            self.depth_reached = min(MAX_DEPTH, self.depth_reached + 1)
            self.attempts_at_depth = 0
            return DepthAction.DEEPEN

        if score >= WEAK_ANSWER:
            self.low_streak = 0
            if self.attempts_at_depth >= 2:
                return DepthAction.SWITCH
            return DepthAction.SIDESTEP

        self.low_streak += 1
        if self.low_streak >= ABANDON_STREAK:
            self.exhausted = True
            self.abandoned_at_depth = max(1, self.depth_reached)
            return DepthAction.ABANDON
        return DepthAction.SIDESTEP

    def summary(self) -> str:
        state = "已放弃深挖" if self.exhausted else f"最深触及 D{max(1, self.depth_reached)}"
        return f"{self.domain}/{self.skill}：{state}，问过 {self.attempts} 次，最佳表现 {self.best_quality:.2f}"


class QuestionBank(BaseModel):
    """面试前一次性生成，面试中只读。导演只能从这里挑新问题。"""

    questions: list[BankQuestion] = Field(default_factory=list)

    def by_id(self, question_id: int) -> BankQuestion | None:
        return next((q for q in self.questions if q.id == question_id), None)

    def domains(self) -> list[str]:
        seen: list[str] = []
        for q in self.questions:
            if q.domain and q.domain not in seen:
                seen.append(q.domain)
        return seen

    def skills(self) -> list[str]:
        seen: list[str] = []
        for q in self.questions:
            if q.skill and q.skill not in seen:
                seen.append(q.skill)
        return seen

    def pending_must_ask(self, asked_ids: set[int]) -> list[BankQuestion]:
        return [q for q in self.questions if q.must_ask and q.id not in asked_ids]

    def candidates(
        self,
        *,
        asked_ids: set[int],
        progress: dict[str, SkillProgress],
        sources: tuple[QuestionSource, ...] | None = None,
        prefer_domain: str | None = None,
        avoid_domains: tuple[str, ...] = (),
        limit: int = 4,
    ) -> list[BankQuestion]:
        pool: list[BankQuestion] = []
        for q in self.questions:
            if q.id in asked_ids:
                continue
            if sources is not None and q.source not in sources:
                continue
            state = progress.get(_key(q.skill))
            if state is not None and state.exhausted:
                continue
            ceiling = state.next_depth if state else 1
            if q.depth > max(1, ceiling):
                continue
            if q.domain in avoid_domains and q.domain != prefer_domain:
                continue
            pool.append(q)

        def rank(q: BankQuestion) -> tuple[int, int, int, int]:
            domain_hit = 0 if (prefer_domain and q.domain == prefer_domain) else 1
            return (0 if q.must_ask else 1, domain_hit, _SOURCE_PRIORITY[q.source], q.depth)

        pool.sort(key=rank)
        return pool[:limit]

    def remaining_count(self, asked_ids: set[int]) -> int:
        return sum(1 for q in self.questions if q.id not in asked_ids)

    def coverage_line(self, asked_ids: set[int]) -> str:
        pending = self.pending_must_ask(asked_ids)
        if not pending:
            return "JD 必问项已全部覆盖"
        return "尚未覆盖的 JD 必问项：" + "、".join(q.skill for q in pending[:6])


def _key(skill: str) -> str:
    return skill.strip().lower()


def progress_for(
    progress: dict[str, SkillProgress], *, skill: str, domain: str
) -> SkillProgress:
    """取或建某技能点的推进状态。字典键统一小写，避免大小写分裂。"""
    key = _key(skill)
    state = progress.get(key)
    if state is None:
        state = SkillProgress(skill=skill.strip(), domain=domain.strip())
        progress[key] = state
    return state
