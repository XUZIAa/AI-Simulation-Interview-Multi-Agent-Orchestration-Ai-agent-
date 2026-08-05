from __future__ import annotations

import logging
from typing import ClassVar

from pydantic import AliasChoices, Field

from ..core.types import GapSeverity, InterviewPhase
from ..domain.resume import (
    GapReport,
    JobDescription,
    ProjectHighlight,
    ResumeProfile,
    SkillGap,
    SkillMatch,
)
from ..llm import prompts
from ..llm.base import system, user
from ..llm.coerce import LooseModel
from ..llm.router import ROLE_ANALYST
from .base import Agent

logger = logging.getLogger(__name__)

_PHASE_KEYS: dict[str, InterviewPhase] = {
    "resume_deep_dive": InterviewPhase.RESUME_DEEP_DIVE,
    "tech_depth": InterviewPhase.TECH_DEPTH,
    "behavioral": InterviewPhase.BEHAVIORAL,
    "coding": InterviewPhase.CODING,
    "stress": InterviewPhase.STRESS,
}


_SKILL_ALIAS = AliasChoices("skill", "requirement", "name", "item", "point", "keyword")


class _ProjectRaw(LooseModel):
    """项目条目。name 在领域模型里必填，这里先收进来再过滤掉无名的。"""

    name: str = Field(default="", validation_alias=AliasChoices("name", "title", "project"))
    role: str = ""
    stack: list[str] = Field(
        default_factory=list, validation_alias=AliasChoices("stack", "tech_stack", "technologies")
    )
    impact: str = Field(default="", validation_alias=AliasChoices("impact", "result", "outcome"))
    summary: str = Field(
        default="", validation_alias=AliasChoices("summary", "description", "desc", "detail")
    )

    def to_domain(self) -> ProjectHighlight | None:
        name = self.name.strip()
        if not name:
            return None
        return ProjectHighlight(
            name=name,
            role=self.role,
            stack=self.stack[:10],
            impact=self.impact,
            summary=self.summary,
        )


class _ResumeRaw(LooseModel):
    candidate_name: str = Field(
        default="", validation_alias=AliasChoices("candidate_name", "name", "candidate")
    )
    years_of_experience: float = Field(
        default=0.0, validation_alias=AliasChoices("years_of_experience", "years", "experience_years")
    )
    current_title: str = Field(
        default="", validation_alias=AliasChoices("current_title", "title", "position")
    )
    education: str = ""
    skills: list[str] = Field(default_factory=list)
    self_claims: list[str] = Field(
        default_factory=list, validation_alias=AliasChoices("self_claims", "claims", "highlights")
    )
    projects: list[_ProjectRaw] = Field(default_factory=list)


class _JobRaw(LooseModel):
    company: str = ""
    title: str = ""
    must_have: list[str] = Field(
        default_factory=list, validation_alias=AliasChoices("must_have", "requirements", "required")
    )
    nice_to_have: list[str] = Field(
        default_factory=list, validation_alias=AliasChoices("nice_to_have", "preferred", "bonus")
    )
    responsibilities: list[str] = Field(
        default_factory=list, validation_alias=AliasChoices("responsibilities", "duties")
    )


class _MatchRaw(LooseModel):
    """已匹配技能。模型常把 skill 写成 requirement，键名要都认。"""

    skill: str = Field(default="", validation_alias=_SKILL_ALIAS)
    evidence: str = Field(default="", validation_alias=AliasChoices("evidence", "proof", "reason"))
    strength: int = 3

    def to_domain(self) -> SkillMatch | None:
        skill = self.skill.strip()
        if not skill:
            return None
        return SkillMatch(skill=skill, evidence=self.evidence, strength=max(1, min(5, self.strength)))


class _GapRawItem(LooseModel):
    skill: str = Field(default="", validation_alias=_SKILL_ALIAS)
    severity: str = "major"
    jd_requirement: str = Field(
        default="", validation_alias=AliasChoices("jd_requirement", "requirement", "jd")
    )
    why_gap: str = Field(default="", validation_alias=AliasChoices("why_gap", "reason", "why"))
    bridge_asset: str = Field(
        default="", validation_alias=AliasChoices("bridge_asset", "bridge", "asset")
    )
    talking_script: str = Field(
        default="", validation_alias=AliasChoices("talking_script", "script", "talking_point")
    )
    study_hint: str = Field(default="", validation_alias=AliasChoices("study_hint", "hint", "study"))


class _GapRaw(LooseModel):
    match_score: int = Field(default=0, validation_alias=AliasChoices("match_score", "score"))
    verdict: str = Field(default="", validation_alias=AliasChoices("verdict", "conclusion", "summary"))
    matches: list[_MatchRaw] = Field(default_factory=list)
    gaps: list[_GapRawItem] = Field(default_factory=list)
    predicted_questions: list[str] = Field(
        default_factory=list, validation_alias=AliasChoices("predicted_questions", "questions")
    )
    focus_skills: list[str] = Field(
        default_factory=list, validation_alias=AliasChoices("focus_skills", "focus")
    )
    phase_emphasis: dict[str, int] = Field(default_factory=dict)


class ResumeAgent(Agent):
    """面试前的资料理解与差距诊断。走强模型，不计延迟。"""

    role: ClassVar[str] = ROLE_ANALYST

    async def parse_resume(self, raw_text: str, *, source_name: str = "") -> ResumeProfile:
        parsed = await self.client.structured(
            [system(prompts.RESUME_EXTRACT), user(raw_text[:20000])],
            _ResumeRaw,
            temperature=0.1,
            max_tokens=4096,
        )
        return ResumeProfile(
            source_name=source_name,
            raw_text=raw_text,
            candidate_name=parsed.candidate_name.strip(),
            years_of_experience=max(0.0, parsed.years_of_experience),
            current_title=parsed.current_title.strip(),
            skills=_unique(parsed.skills)[:40],
            projects=[p for p in (raw.to_domain() for raw in parsed.projects) if p][:6],
            education=parsed.education.strip(),
            self_claims=[c.strip() for c in parsed.self_claims if c.strip()][:10],
        )

    async def parse_job(self, raw_text: str, *, source_name: str = "") -> JobDescription:
        parsed = await self.client.structured(
            [system(prompts.JD_EXTRACT), user(raw_text[:12000])],
            _JobRaw,
            temperature=0.1,
            max_tokens=2000,
        )
        return JobDescription(
            source_name=source_name,
            raw_text=raw_text,
            company=parsed.company.strip(),
            title=parsed.title.strip(),
            must_have=_unique(parsed.must_have)[:25],
            nice_to_have=_unique(parsed.nice_to_have)[:20],
            responsibilities=[r.strip() for r in parsed.responsibilities if r.strip()][:12],
        )

    async def analyze_gap(self, resume: ResumeProfile, job: JobDescription) -> GapReport:
        parsed = await self.client.structured(
            [
                system(prompts.GAP_ANALYSIS),
                user(prompts.gap_user_prompt(resume.raw_text, job.raw_text)),
            ],
            _GapRaw,
            temperature=0.35,
            max_tokens=6000,
        )
        gaps = [
            SkillGap(
                skill=item.skill.strip(),
                severity=_severity(item.severity),
                jd_requirement=item.jd_requirement.strip(),
                why_gap=item.why_gap.strip(),
                bridge_asset=item.bridge_asset.strip(),
                talking_script=item.talking_script.strip(),
                study_hint=item.study_hint.strip(),
            )
            for item in parsed.gaps
            if item.skill.strip()
        ]
        emphasis = {
            _PHASE_KEYS[key]: max(0, min(5, value))
            for key, value in parsed.phase_emphasis.items()
            if key in _PHASE_KEYS
        }
        matches = [m for m in (raw.to_domain() for raw in parsed.matches) if m][:20]
        focus = _unique(parsed.focus_skills)[:12]
        if not focus:
            focus = _unique([g.skill for g in gaps] + [m.skill for m in matches])[:10]
        return GapReport(
            match_score=max(0, min(100, parsed.match_score)),
            verdict=parsed.verdict.strip(),
            matches=matches,
            gaps=sorted(gaps, key=lambda g: _SEVERITY_ORDER[g.severity])[:12],
            predicted_questions=[q.strip() for q in parsed.predicted_questions if q.strip()][:10],
            focus_skills=focus,
            phase_emphasis=emphasis,
        )


_SEVERITY_ORDER: dict[GapSeverity, int] = {
    GapSeverity.BLOCKER: 0,
    GapSeverity.MAJOR: 1,
    GapSeverity.MINOR: 2,
}


def _severity(value: str) -> GapSeverity:
    try:
        return GapSeverity(value.strip().lower())
    except ValueError:
        return GapSeverity.MAJOR


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = value.strip()
        key = text.lower()
        if not text or key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result
