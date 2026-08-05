from __future__ import annotations

from pydantic import BaseModel, Field

from ..core.types import GapSeverity, InterviewPhase


class ProjectHighlight(BaseModel):
    name: str
    role: str = ""
    stack: list[str] = Field(default_factory=list)
    impact: str = ""
    summary: str = ""


class ResumeProfile(BaseModel):
    """从简历原文抽出的结构化画像，后续所有个性化都基于它。"""

    source_name: str = ""
    raw_text: str = ""
    candidate_name: str = ""
    years_of_experience: float = 0.0
    current_title: str = ""
    skills: list[str] = Field(default_factory=list)
    projects: list[ProjectHighlight] = Field(default_factory=list)
    education: str = ""
    self_claims: list[str] = Field(default_factory=list)

    def is_empty(self) -> bool:
        return not self.raw_text.strip()

    def compact(self, limit: int = 1600) -> str:
        """给模型的压缩画像，避免每轮塞全文。"""
        parts: list[str] = []
        if self.candidate_name:
            parts.append(f"候选人：{self.candidate_name}")
        if self.current_title:
            parts.append(f"当前职位：{self.current_title}")
        if self.years_of_experience:
            parts.append(f"经验年限：{self.years_of_experience:g} 年")
        if self.skills:
            parts.append("技能栈：" + "、".join(self.skills[:24]))
        for proj in self.projects[:4]:
            stack = f"（{'/'.join(proj.stack[:6])}）" if proj.stack else ""
            impact = f" 产出：{proj.impact}" if proj.impact else ""
            parts.append(f"项目「{proj.name}」{stack} 角色：{proj.role or '未说明'}。{proj.summary}{impact}")
        if self.education:
            parts.append(f"教育：{self.education}")
        text = "\n".join(parts)
        return text[:limit]


class JobDescription(BaseModel):
    source_name: str = ""
    raw_text: str = ""
    company: str = ""
    title: str = ""
    must_have: list[str] = Field(default_factory=list)
    nice_to_have: list[str] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)

    def is_empty(self) -> bool:
        return not self.raw_text.strip()

    def compact(self, limit: int = 1200) -> str:
        parts: list[str] = []
        if self.company or self.title:
            parts.append(f"目标岗位：{self.company} {self.title}".strip())
        if self.must_have:
            parts.append("硬性要求：" + "、".join(self.must_have[:16]))
        if self.nice_to_have:
            parts.append("加分项：" + "、".join(self.nice_to_have[:12]))
        if self.responsibilities:
            parts.append("职责：" + "；".join(self.responsibilities[:8]))
        return "\n".join(parts)[:limit]


class SkillMatch(BaseModel):
    skill: str
    evidence: str = ""
    strength: int = Field(default=3, ge=1, le=5)


class SkillGap(BaseModel):
    """技能盲区 + 可直接照着说的补救话术。"""

    skill: str
    severity: GapSeverity = GapSeverity.MAJOR
    jd_requirement: str = ""
    why_gap: str = ""
    bridge_asset: str = ""
    talking_script: str = ""
    study_hint: str = ""


class GapReport(BaseModel):
    match_score: int = Field(default=0, ge=0, le=100)
    verdict: str = ""
    matches: list[SkillMatch] = Field(default_factory=list)
    gaps: list[SkillGap] = Field(default_factory=list)
    predicted_questions: list[str] = Field(default_factory=list)
    focus_skills: list[str] = Field(default_factory=list)
    phase_emphasis: dict[InterviewPhase, int] = Field(default_factory=dict)

    def blockers(self) -> list[SkillGap]:
        return [g for g in self.gaps if g.severity is GapSeverity.BLOCKER]

    def compact(self, limit: int = 900) -> str:
        lines: list[str] = []
        if self.verdict:
            lines.append(f"匹配度 {self.match_score}/100：{self.verdict}")
        if self.gaps:
            lines.append("已知盲区（面试中重点验证）：")
            lines += [f"- {g.skill}｜{g.severity.label}｜{g.why_gap}" for g in self.gaps[:6]]
        if self.focus_skills:
            lines.append("必须考到的技能点：" + "、".join(self.focus_skills[:10]))
        return "\n".join(lines)[:limit]
