from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel
from pydantic import Field as PydField

from ..core.types import ScoreDimension, TurnIntent
from .question_bank import BankQuestion, DepthAction

NEW_QUESTION_INTENTS: frozenset[TurnIntent] = frozenset(
    {TurnIntent.ASK_NEW, TurnIntent.CODING_HANDOFF}
)
PROBE_INTENTS: frozenset[TurnIntent] = frozenset(
    {TurnIntent.FOLLOW_UP, TurnIntent.STAR_PROBE, TurnIntent.BOUNDARY_TEST}
)


class DirectorDecision(BaseModel):
    """导演的一条指令。面试官只执行 brief，不知道其余字段。"""

    intent: TurnIntent
    brief: str
    target_skill: str = ""
    domain: str = ""
    depth: int = 1
    chosen_question: BankQuestion | None = None
    is_personality: bool = False
    should_advance_phase: bool = False
    should_interrupt: bool = False
    answer_quality: float | None = None
    answer_summary: str = ""
    covered_skills: list[str] = PydField(default_factory=list)
    dimension_deltas: dict[ScoreDimension, float] = PydField(default_factory=dict)


@dataclass(slots=True)
class TurnPlan:
    """本轮的硬边界。由确定性规则算出，导演只能在这个范围内做选择。"""

    allowed_intents: list[TurnIntent]
    candidates: list[BankQuestion] = field(default_factory=list)
    depth_action: DepthAction | None = None
    phase_hint: str = ""
    interrupt_allowed: bool = False
    follow_up_allowed: bool = False
    force_personality: bool = False
    must_close: bool = False
    prefer_domain: str | None = None
    avoid_domains: tuple[str, ...] = ()

    def candidate_block(self) -> str:
        if not self.candidates:
            return "（题库中当前没有可用的新问题，只能追问、过渡或收尾）"
        lines = ["可选的新问题（新问题必须从这里选，把编号填进 chosen_question_id）："]
        lines += [f"- {q.one_line()}" for q in self.candidates]
        return "\n".join(lines)
