from __future__ import annotations

import logging
import shutil
from collections.abc import Callable
from pathlib import Path

from ..agents.prepare_agents import BankBuilder, JobSynthesizer
from ..agents.resume_agent import ResumeAgent
from ..core.paths import resume_dir
from ..core.types import CompanyTier, JobLevel
from ..data.repositories.library_repo import LibraryRepository, StoredGap, StoredJob, StoredResume
from ..data.repositories.persona_repo import PersonaRepository
from ..data.repositories.session_repo import SessionRepository
from ..domain.interview import InterviewState, build_plan
from ..domain.persona import PersonaContract
from ..domain.question_bank import QuestionBank
from ..domain.resume import JobDescription
from ..ingest.documents import read_document
from ..llm.router import LLMRouter

logger = logging.getLogger(__name__)

Progress = Callable[[str, int], None]


def _noop(_stage: str, _percent: int) -> None:
    return


class PrepareService:
    """面试前的资料处理与开场准备。所有耗时步骤都上报进度。"""

    def __init__(
        self,
        *,
        router: LLMRouter,
        library: LibraryRepository,
        sessions: SessionRepository,
        personas: PersonaRepository,
    ) -> None:
        self._resume_agent = ResumeAgent(router)
        self._job_synth = JobSynthesizer(router)
        self._bank_builder = BankBuilder(router)
        self._library = library
        self._sessions = sessions
        self._personas = personas

    # ---------- 资料摄取 ----------

    async def ingest_resume(self, path: Path, *, on_progress: Progress = _noop) -> StoredResume:
        on_progress("正在读取简历文件", 10)
        raw = read_document(path)
        stored_copy = resume_dir() / path.name
        if path.resolve() != stored_copy.resolve():
            shutil.copy2(path, stored_copy)
        on_progress("正在结构化解析简历", 40)
        profile = await self._resume_agent.parse_resume(raw, source_name=path.name)
        on_progress("正在保存", 85)
        stored = await self._library.save_resume(
            profile, label=profile.candidate_name or path.stem, file_path=str(stored_copy)
        )
        on_progress("简历已就绪", 100)
        return stored

    async def ingest_job_file(self, path: Path, *, on_progress: Progress = _noop) -> StoredJob:
        on_progress("正在读取 JD 文件", 15)
        raw = read_document(path)
        on_progress("正在结构化解析 JD", 50)
        jd = await self._resume_agent.parse_job(raw, source_name=path.name)
        on_progress("正在保存", 85)
        stored = await self._library.save_job(jd, label=_job_label(jd, path.stem))
        on_progress("岗位已就绪", 100)
        return stored

    async def ingest_job_text(self, raw: str, *, on_progress: Progress = _noop) -> StoredJob:
        on_progress("正在结构化解析 JD", 40)
        jd = await self._resume_agent.parse_job(raw, source_name="手动粘贴")
        stored = await self._library.save_job(jd, label=_job_label(jd, "手动粘贴的 JD"))
        on_progress("岗位已就绪", 100)
        return stored

    async def synthesize_job(
        self,
        *,
        title: str,
        tier: CompanyTier,
        level: JobLevel,
        extra: str = "",
        on_progress: Progress = _noop,
    ) -> StoredJob:
        """只给岗位名称时，按公司类型合成一份贴合市场的 JD。"""
        on_progress("正在生成岗位描述", 30)
        jd = await self._job_synth.synthesize(title=title, tier=tier, level=level, extra=extra)
        on_progress("正在保存", 85)
        stored = await self._library.save_job(jd, label=f"{jd.title}·{tier.label}")
        on_progress("岗位已就绪", 100)
        return stored

    # ---------- 差距诊断 ----------

    async def diagnose(
        self, *, resume_id: int, job_id: int, refresh: bool = False, on_progress: Progress = _noop
    ) -> StoredGap:
        if not refresh:
            cached = await self._library.find_gap(resume_id, job_id)
            if cached is not None:
                on_progress("已加载上次诊断结果", 100)
                return cached

        resume = await self._library.get_resume(resume_id)
        job = await self._library.get_job(job_id)
        if resume is None or job is None:
            raise ValueError("简历或岗位不存在")

        on_progress("正在逐条比对 JD 与简历", 35)
        report = await self._resume_agent.analyze_gap(resume.profile, job.description)
        on_progress("正在保存诊断结果", 85)
        stored = await self._library.save_gap(report, resume_id=resume_id, job_id=job_id)
        on_progress("诊断完成", 100)
        return stored

    # ---------- 开场准备 ----------

    async def build_session(
        self,
        *,
        persona: PersonaContract,
        resume_id: int | None,
        job_id: int | None,
        tier: CompanyTier,
        level: JobLevel,
        minutes: int,
        coding_enabled: bool,
        on_progress: Progress = _noop,
    ) -> InterviewState:
        resume = await self._library.get_resume(resume_id) if resume_id else None
        job = await self._library.get_job(job_id) if job_id else None
        gap = None
        if resume_id and job_id:
            gap = await self._library.find_gap(resume_id, job_id)

        title = job.description.title if job else ""
        on_progress("正在排定面试流程", 15)
        plan = build_plan(persona, minutes, coding_enabled=coding_enabled, gap=gap.report if gap else None)

        bank = QuestionBank()
        if resume is not None and job is not None:
            on_progress("正在基于 JD 与简历生成题库", 35)
            bank = await self._bank_builder.build(
                resume=resume.profile,
                job=job.description,
                gap=gap.report if gap else None,
                tier=tier,
                level=level,
                minutes=minutes,
                coding_enabled=coding_enabled,
                on_step=on_progress,
            )

        on_progress("正在创建面试记录", 80)
        session_title = _session_title(title, persona.name, tier)
        session_id = await self._sessions.create(
            title=session_title,
            persona=persona,
            planned_minutes=minutes,
            resume_id=resume_id,
            job_id=job_id,
        )
        if persona.id is not None:
            await self._personas.bump_usage(persona.id)

        gap_report = gap.report if gap else None
        state = InterviewState(
            session_id=session_id,
            persona=persona,
            plan=plan,
            bank=bank,
            company_tier=tier,
            job_level=level,
            job_title=title,
            resume_digest=resume.profile.compact() if resume else "",
            jd_digest=job.description.compact() if job else "",
            gap_digest=gap_report.compact() if gap_report else "",
            pending_skills=list(gap_report.focus_skills) if gap_report else bank.skills()[:8],
        )
        await self._sessions.persist_state(state)
        on_progress("准备完成", 100)
        logger.info(
            "面试已准备 session=%s 题库=%d 计划=%d分钟", session_id, len(bank.questions), minutes
        )
        return state


def _job_label(job: JobDescription, fallback: str) -> str:
    parts = [p for p in (job.company, job.title) if p]
    return " · ".join(parts) if parts else fallback


def _session_title(job_title: str, persona_name: str, tier: CompanyTier) -> str:
    head = job_title or "综合面试"
    return f"{head}｜{tier.label}｜{persona_name}"
