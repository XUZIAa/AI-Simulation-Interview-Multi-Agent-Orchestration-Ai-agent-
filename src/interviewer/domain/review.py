from __future__ import annotations

from pydantic import BaseModel, Field

from ..core.types import AnnotationKind, GapSeverity, ScoreDimension


class DimensionScore(BaseModel):
    dimension: ScoreDimension
    score: float = Field(default=0.0, ge=0.0, le=100.0)
    reason: str = ""
    evidence: list[str] = Field(default_factory=list)


class TranscriptAnnotation(BaseModel):
    """逐字稿上的高亮批注，锚定到具体轮次与原文片段。"""

    turn_index: int
    kind: AnnotationKind
    quote: str = ""
    comment: str = ""


class AnswerRewrite(BaseModel):
    question_index: int
    question: str
    original: str
    rewritten: str
    why_better: list[str] = Field(default_factory=list)
    used_assets: list[str] = Field(default_factory=list)


class MistakeItem(BaseModel):
    knowledge_point: str
    topic: str = ""
    question: str = ""
    candidate_answer: str = ""
    key_points: list[str] = Field(default_factory=list)
    severity: GapSeverity = GapSeverity.MAJOR
    review_hint: str = ""


class QuestionProsody(BaseModel):
    question_index: int
    words_per_minute: float = 0.0
    filler_count: int = 0
    pause_ratio: float = 0.0
    longest_pause_ms: int = 0


class ProsodyReport(BaseModel):
    """副语言指标全部由规则计算，不交给模型编造。"""

    words_per_minute: float = 0.0
    filler_ratio: float = 0.0
    pause_ratio: float = 0.0
    longest_pause_ms: int = 0
    speaking_ratio: float = 0.0
    interrupted_count: int = 0
    per_question: list[QuestionProsody] = Field(default_factory=list)
    verdict: str = ""

    def worst_question(self) -> QuestionProsody | None:
        if not self.per_question:
            return None
        return max(self.per_question, key=lambda q: (q.words_per_minute, q.pause_ratio))


class DrillItem(BaseModel):
    action: str
    why: str = ""
    time_cost: str = ""


class ImprovementPlan(BaseModel):
    """专项提升方案。一个专项对应一条明确的训练路径，不给泛泛建议。"""

    focus_area: str
    diagnosis: str = ""
    expected_gain: str = ""
    drills: list[DrillItem] = Field(default_factory=list)
    resources: list[str] = Field(default_factory=list)
    next_mock_setup: str = ""


class AbandonedSkill(BaseModel):
    """面试中被放弃深挖的技能点。这是最该补的短板。"""

    skill: str
    domain: str = ""
    abandoned_at_depth: int = 1
    attempts: int = 0


class ReviewReport(BaseModel):
    session_id: int
    duration_ms: int = 0
    reviewable: bool = True
    overall_score: float = Field(default=0.0, ge=0.0, le=100.0)
    headline: str = ""
    summary: str = ""
    dimensions: list[DimensionScore] = Field(default_factory=list)
    annotations: list[TranscriptAnnotation] = Field(default_factory=list)
    rewrites: list[AnswerRewrite] = Field(default_factory=list)
    mistakes: list[MistakeItem] = Field(default_factory=list)
    prosody: ProsodyReport = Field(default_factory=ProsodyReport)
    strengths: list[str] = Field(default_factory=list)
    improvements: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    improvement_plans: list[ImprovementPlan] = Field(default_factory=list)
    abandoned_skills: list[AbandonedSkill] = Field(default_factory=list)

    def score_map(self) -> dict[ScoreDimension, float]:
        return {d.dimension: d.score for d in self.dimensions}

    def annotations_for(self, turn_index: int) -> list[TranscriptAnnotation]:
        return [a for a in self.annotations if a.turn_index == turn_index]
