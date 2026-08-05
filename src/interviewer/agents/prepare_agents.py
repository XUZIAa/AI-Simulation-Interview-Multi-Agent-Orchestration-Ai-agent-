from __future__ import annotations

import logging
from typing import ClassVar

from pydantic import BaseModel, Field

from ..core.types import MAX_DEPTH, CompanyTier, JobLevel, QuestionSource
from ..domain.company import company_profile, level_expectation
from ..domain.question_bank import BankQuestion, QuestionBank
from ..domain.resume import GapReport, JobDescription, ResumeProfile
from ..llm import prompts
from ..llm.base import system, user
from ..llm.router import ROLE_ANALYST
from .base import Agent, trim

logger = logging.getLogger(__name__)


class _JobSynthRaw(BaseModel):
    company: str = ""
    title: str = ""
    must_have: list[str] = Field(default_factory=list)
    nice_to_have: list[str] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)


class JobSynthesizer(Agent):
    """只给岗位名称时合成一份贴合市场实际的 JD。"""

    role: ClassVar[str] = ROLE_ANALYST

    async def synthesize(
        self,
        *,
        title: str,
        tier: CompanyTier,
        level: JobLevel,
        extra: str = "",
    ) -> JobDescription:
        profile = company_profile(tier)
        raw = await self.client.structured(
            [
                system(prompts.JD_SYNTH),
                user(
                    prompts.jd_synth_prompt(
                        title=title,
                        tier_label=tier.label,
                        tier_flavor=profile.jd_flavor,
                        level_label=level.label,
                        extra=extra,
                    )
                ),
            ],
            _JobSynthRaw,
            temperature=0.45,
            max_tokens=2500,
        )
        must_have = _clean(raw.must_have, 40)[:9]
        nice = _clean(raw.nice_to_have, 40)[:6]
        duties = _clean(raw.responsibilities, 60)[:6]
        company = raw.company.strip() or f"某{tier.label}"
        resolved_title = raw.title.strip() or title.strip()

        lines = [f"{company} · {resolved_title}（{level.label}）", ""]
        if duties:
            lines += ["岗位职责：", *(f"{i}. {d}" for i, d in enumerate(duties, 1)), ""]
        if must_have:
            lines += ["任职要求：", *(f"{i}. {m}" for i, m in enumerate(must_have, 1)), ""]
        if nice:
            lines += ["加分项：", *(f"- {n}" for n in nice)]

        return JobDescription(
            source_name=f"{resolved_title}（一键生成）",
            raw_text="\n".join(lines).strip(),
            company=company,
            title=resolved_title,
            must_have=must_have,
            nice_to_have=nice,
            responsibilities=duties,
        )


class _BankItemRaw(BaseModel):
    text: str = ""
    skill: str = ""
    domain: str = ""
    depth: int = 1
    source: str = "fundamental"
    project_ref: str = ""
    jd_ref: str = ""
    follow_ups: list[str] = Field(default_factory=list)
    expected_signals: list[str] = Field(default_factory=list)
    must_ask: bool = False


class _BankRaw(BaseModel):
    questions: list[_BankItemRaw] = Field(default_factory=list)


class BankBuilder(Agent):
    """面试前构建题库。技术题与软性题分两次生成，避免单次输出过长而截断。"""

    role: ClassVar[str] = ROLE_ANALYST

    async def build(
        self,
        *,
        resume: ResumeProfile,
        job: JobDescription,
        gap: GapReport | None,
        tier: CompanyTier,
        level: JobLevel,
        minutes: int,
        coding_enabled: bool,
    ) -> QuestionBank:
        context = prompts.bank_user_prompt(
            jd_digest=job.compact(1600),
            resume_digest=resume.compact(2200),
            company_block=company_profile(tier).guidance_block(),
            level_expectation=level_expectation(tier, level),
            gap_digest=gap.compact(900) if gap else "",
            coding_enabled=coding_enabled,
            minutes=minutes,
        )

        tech = await self._generate(prompts.BANK_TECH_SYSTEM, context, max_tokens=9000)
        soft = await self._generate(prompts.BANK_SOFT_SYSTEM, context, max_tokens=5000)

        questions: list[BankQuestion] = []
        next_id = 1
        seen: set[str] = set()
        for item in [*tech.questions, *soft.questions]:
            built = _to_question(item, next_id, coding_enabled=coding_enabled)
            if built is None:
                continue
            fingerprint = built.text[:40].lower()
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            questions.append(built)
            next_id += 1

        if gap:
            _apply_must_ask(questions, gap)
        bank = QuestionBank(questions=questions)
        logger.info(
            "题库构建完成：%d 道，领域 %s，必问 %d",
            len(questions),
            "/".join(bank.domains()[:8]),
            len(bank.pending_must_ask(set())),
        )
        return bank

    async def _generate(self, instruction: str, context: str, *, max_tokens: int) -> _BankRaw:
        return await self.client.structured(
            [system(instruction), user(context)],
            _BankRaw,
            temperature=0.55,
            max_tokens=max_tokens,
        )


def _to_question(item: _BankItemRaw, question_id: int, *, coding_enabled: bool) -> BankQuestion | None:
    text = trim(item.text, 160)
    if len(text) < 6:
        return None
    try:
        source = QuestionSource(item.source.strip().lower())
    except ValueError:
        source = QuestionSource.FUNDAMENTAL
    if source is QuestionSource.CODING and not coding_enabled:
        return None
    skill = trim(item.skill, 40) or trim(item.domain, 40) or "综合"
    domain = trim(item.domain, 30) or _DEFAULT_DOMAIN.get(source, "综合")
    return BankQuestion(
        id=question_id,
        text=text,
        skill=skill,
        domain=domain,
        depth=max(1, min(MAX_DEPTH, item.depth)),
        source=source,
        project_ref=trim(item.project_ref, 40),
        jd_ref=trim(item.jd_ref, 60),
        follow_ups=[trim(f, 40) for f in item.follow_ups if f.strip()][:3],
        expected_signals=[trim(s, 50) for s in item.expected_signals if s.strip()][:4],
        must_ask=item.must_ask,
    )


_DEFAULT_DOMAIN: dict[QuestionSource, str] = {
    QuestionSource.BEHAVIORAL: "行为与价值观",
    QuestionSource.CODING: "编码",
    QuestionSource.RESUME_PROJECT: "项目经历",
}


def _apply_must_ask(questions: list[BankQuestion], gap: GapReport) -> None:
    """诊断出的致命缺口对应的题目，强制标为必问。"""
    blockers = {g.skill.strip().lower() for g in gap.blockers()}
    focus = {s.strip().lower() for s in gap.focus_skills}
    for question in questions:
        key = question.skill.strip().lower()
        is_focus_entry = (
            key in focus
            and question.source is QuestionSource.JD_REQUIREMENT
            and question.depth <= 2
        )
        if key in blockers or is_focus_entry:
            question.must_ask = True


def _clean(values: list[str], limit: int) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = trim(value, limit)
        key = text.lower()
        if not text or key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result
