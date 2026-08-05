from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select

from ...domain.resume import GapReport, JobDescription, ResumeProfile
from ..database import Database
from ..models import GapReportRow, JobRow, ResumeRow
from .base import Repository


@dataclass(slots=True)
class StoredResume:
    id: int
    label: str
    file_path: str
    profile: ResumeProfile


@dataclass(slots=True)
class StoredJob:
    id: int
    label: str
    description: JobDescription


@dataclass(slots=True)
class StoredGap:
    id: int
    resume_id: int
    job_id: int
    report: GapReport


class LibraryRepository:
    """简历、JD、差距报告三者的存取。三张表分开写，避免长事务。"""

    def __init__(self) -> None:
        self._repo = Repository()

    @property
    def db(self) -> Database:
        return self._repo.db

    # ---------- 简历 ----------

    async def save_resume(self, profile: ResumeProfile, *, label: str, file_path: str = "") -> StoredResume:
        async with self.db.transaction() as session:
            row = ResumeRow(label=label, file_path=file_path, payload=profile.model_dump(mode="json"))
            session.add(row)
            await session.flush()
            row_id = row.id
        return StoredResume(id=row_id, label=label, file_path=file_path, profile=profile)

    async def list_resumes(self, limit: int = 30) -> list[StoredResume]:
        async with self.db.session() as session:
            stmt = select(ResumeRow).order_by(ResumeRow.created_at.desc()).limit(limit)
            rows = (await session.execute(stmt)).scalars().all()
        return [
            StoredResume(
                id=r.id,
                label=r.label,
                file_path=r.file_path,
                profile=ResumeProfile.model_validate(r.payload),
            )
            for r in rows
        ]

    async def get_resume(self, resume_id: int) -> StoredResume | None:
        async with self.db.session() as session:
            row = await session.get(ResumeRow, resume_id)
        if row is None:
            return None
        return StoredResume(
            id=row.id,
            label=row.label,
            file_path=row.file_path,
            profile=ResumeProfile.model_validate(row.payload),
        )

    async def delete_resume(self, resume_id: int) -> None:
        async with self.db.transaction() as session:
            row = await session.get(ResumeRow, resume_id)
            if row is not None:
                await session.delete(row)

    # ---------- JD ----------

    async def save_job(self, jd: JobDescription, *, label: str) -> StoredJob:
        async with self.db.transaction() as session:
            row = JobRow(
                label=label,
                company=jd.company,
                title=jd.title,
                payload=jd.model_dump(mode="json"),
            )
            session.add(row)
            await session.flush()
            row_id = row.id
        return StoredJob(id=row_id, label=label, description=jd)

    async def list_jobs(self, limit: int = 30) -> list[StoredJob]:
        async with self.db.session() as session:
            stmt = select(JobRow).order_by(JobRow.created_at.desc()).limit(limit)
            rows = (await session.execute(stmt)).scalars().all()
        return [
            StoredJob(id=r.id, label=r.label, description=JobDescription.model_validate(r.payload))
            for r in rows
        ]

    async def get_job(self, job_id: int) -> StoredJob | None:
        async with self.db.session() as session:
            row = await session.get(JobRow, job_id)
        if row is None:
            return None
        return StoredJob(id=row.id, label=row.label, description=JobDescription.model_validate(row.payload))

    async def delete_job(self, job_id: int) -> None:
        async with self.db.transaction() as session:
            row = await session.get(JobRow, job_id)
            if row is not None:
                await session.delete(row)

    # ---------- 差距报告 ----------

    async def save_gap(self, report: GapReport, *, resume_id: int, job_id: int) -> StoredGap:
        async with self.db.transaction() as session:
            stmt = select(GapReportRow).where(
                GapReportRow.resume_id == resume_id, GapReportRow.job_id == job_id
            )
            row = (await session.execute(stmt)).scalar_one_or_none()
            payload = report.model_dump(mode="json")
            if row is None:
                row = GapReportRow(
                    resume_id=resume_id,
                    job_id=job_id,
                    match_score=report.match_score,
                    payload=payload,
                )
                session.add(row)
                await session.flush()
            else:
                row.match_score = report.match_score
                row.payload = payload
            row_id = row.id
        return StoredGap(id=row_id, resume_id=resume_id, job_id=job_id, report=report)

    async def find_gap(self, resume_id: int, job_id: int) -> StoredGap | None:
        async with self.db.session() as session:
            stmt = select(GapReportRow).where(
                GapReportRow.resume_id == resume_id, GapReportRow.job_id == job_id
            )
            row = (await session.execute(stmt)).scalar_one_or_none()
        if row is None:
            return None
        return StoredGap(
            id=row.id,
            resume_id=row.resume_id,
            job_id=row.job_id,
            report=GapReport.model_validate(row.payload),
        )
