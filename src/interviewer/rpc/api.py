from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from ..app.context import AppContext
from ..core.config import AppSettings
from ..core.errors import InterviewerError
from ..core.types import ScoreDimension, SessionStatus
from ..data.repositories.library_repo import StoredGap, StoredJob, StoredResume
from ..data.repositories.review_repo import StoredMistake, TrendPoint
from ..data.repositories.session_repo import GlobalStats, SessionSummary
from ..domain.interview import InterviewState, TurnRecord
from ..domain.persona import PersonaContract
from ..domain.review import ReviewReport
from ..orchestration.recovery import InterruptedSession
from .hub import EventHub
from .schemas import (
    ApiKeyBody,
    BuildSessionBody,
    DiagnoseBody,
    GenerateReviewBody,
    HintBody,
    IngestJobTextBody,
    IngestPathBody,
    MistakeCounts,
    MuteBody,
    Ok,
    ServerInfo,
    SetMasteredBody,
    StartInterviewBody,
    StopInterviewBody,
    StopResult,
    SubmitCodeBody,
    SynthesizeJobBody,
    TaskBody,
    UniqueNameBody,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _ctx(request: Request) -> AppContext:
    return request.app.state.ctx


def _hub(request: Request) -> EventHub:
    return request.app.state.hub


def _progress(hub: EventHub, body: TaskBody):
    """把同步进度回调转成 WS 事件。回调在业务代码里同步调用，不能阻塞。"""

    def report(stage: str, percent: int) -> None:
        hub.publish("task_progress", {"task_id": body.task_id, "stage": stage, "percent": percent})

    return report


# ==================================================================
# 元信息
# ==================================================================


@router.get("/info", response_model=ServerInfo, tags=["meta"])
async def info(request: Request) -> ServerInfo:
    from .hub import EVENT_NAMES

    return ServerInfo(
        name="interviewer-rpc",
        version="1",
        event_names=list(EVENT_NAMES),
        subscribers=_hub(request).client_count,
    )


# ==================================================================
# 面试引擎
# ==================================================================


@router.post("/engine/start", response_model=Ok, tags=["engine"])
async def engine_start(request: Request, body: StartInterviewBody) -> Ok:
    ctx = _ctx(request)
    state = await ctx.sessions.load_state(body.session_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"找不到会话 {body.session_id}")
    await ctx.engine.start(state)
    return Ok()


@router.post("/engine/stop", response_model=StopResult, tags=["engine"])
async def engine_stop(request: Request, body: StopInterviewBody) -> StopResult:
    state = await _ctx(request).engine.stop(aborted=body.aborted)
    if state is None:
        return StopResult()
    return StopResult(
        session_id=state.session_id, reviewable=state.reviewable, elapsed_ms=state.elapsed_ms
    )


@router.post("/engine/wait-finished", response_model=Ok, tags=["engine"])
async def engine_wait_finished(request: Request) -> Ok:
    """面试从开始到结束都挂在这个请求上，正常要等几十分钟。"""
    await _ctx(request).engine.wait_finished()
    return Ok()


@router.post("/engine/mute", response_model=Ok, tags=["engine"])
async def engine_mute(request: Request, body: MuteBody) -> Ok:
    _ctx(request).engine.set_muted(body.muted)
    return Ok()


@router.post("/engine/hint", response_model=Ok, tags=["engine"])
async def engine_hint(request: Request, body: HintBody) -> Ok:
    await _ctx(request).engine.request_hint(auto=body.auto)
    return Ok()


@router.post("/engine/interrupt", response_model=Ok, tags=["engine"])
async def engine_interrupt(request: Request) -> Ok:
    await _ctx(request).engine.interrupt_interviewer()
    return Ok()


@router.post("/engine/code", response_model=Ok, tags=["engine"])
async def engine_submit_code(request: Request, body: SubmitCodeBody) -> Ok:
    await _ctx(request).engine.submit_code(body.language, body.source)
    return Ok()


@router.post("/engine/finish-early", response_model=Ok, tags=["engine"])
async def engine_finish_early(request: Request) -> Ok:
    await _ctx(request).engine.finish_early()
    return Ok()


# ==================================================================
# 面试准备
# ==================================================================


@router.post("/prepare/session", response_model=InterviewState, tags=["prepare"])
async def prepare_build_session(request: Request, body: BuildSessionBody) -> Any:
    state = await _ctx(request).prepare.build_session(
        persona=body.persona,
        resume_id=body.resume_id,
        job_id=body.job_id,
        tier=body.tier,
        level=body.level,
        minutes=body.minutes,
        coding_enabled=body.coding_enabled,
        on_progress=_progress(_hub(request), body),
    )
    return state


@router.post("/prepare/resume", response_model=StoredResume, tags=["prepare"])
async def prepare_ingest_resume(request: Request, body: IngestPathBody) -> Any:
    from pathlib import Path

    return await _ctx(request).prepare.ingest_resume(
        Path(body.path), on_progress=_progress(_hub(request), body)
    )


@router.post("/prepare/job-file", response_model=StoredJob, tags=["prepare"])
async def prepare_ingest_job_file(request: Request, body: IngestPathBody) -> Any:
    from pathlib import Path

    return await _ctx(request).prepare.ingest_job_file(
        Path(body.path), on_progress=_progress(_hub(request), body)
    )


@router.post("/prepare/job-text", response_model=StoredJob, tags=["prepare"])
async def prepare_ingest_job_text(request: Request, body: IngestJobTextBody) -> Any:
    return await _ctx(request).prepare.ingest_job_text(
        body.raw, on_progress=_progress(_hub(request), body)
    )


@router.post("/prepare/job-synthesize", response_model=StoredJob, tags=["prepare"])
async def prepare_synthesize_job(request: Request, body: SynthesizeJobBody) -> Any:
    return await _ctx(request).prepare.synthesize_job(
        title=body.title,
        tier=body.tier,
        level=body.level,
        extra=body.extra,
        on_progress=_progress(_hub(request), body),
    )


@router.post("/prepare/diagnose", response_model=StoredGap, tags=["prepare"])
async def prepare_diagnose(request: Request, body: DiagnoseBody) -> Any:
    return await _ctx(request).prepare.diagnose(
        resume_id=body.resume_id,
        job_id=body.job_id,
        refresh=body.refresh,
        on_progress=_progress(_hub(request), body),
    )


# ==================================================================
# 复盘
# ==================================================================


@router.post("/review/generate", response_model=ReviewReport, tags=["review"])
async def review_generate(request: Request, body: GenerateReviewBody) -> Any:
    ctx = _ctx(request)
    state = await ctx.sessions.load_state(body.session_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"找不到会话 {body.session_id}")
    return await ctx.review.generate(state)


@router.get("/review/{session_id}", response_model=ReviewReport | None, tags=["review"])
async def review_load(request: Request, session_id: int) -> Any:
    return await _ctx(request).review.load(session_id)


# ==================================================================
# 会话
# ==================================================================


@router.get("/sessions", response_model=list[SessionSummary], tags=["sessions"])
async def sessions_list(request: Request, limit: int = Query(default=50, ge=1, le=200)) -> Any:
    return await _ctx(request).sessions.list_recent(limit=limit)


@router.get("/sessions/stats", response_model=GlobalStats, tags=["sessions"])
async def sessions_stats(request: Request) -> Any:
    return await _ctx(request).sessions.stats()


@router.get("/sessions/{session_id}/state", response_model=InterviewState | None, tags=["sessions"])
async def sessions_state(request: Request, session_id: int) -> Any:
    return await _ctx(request).sessions.load_state(session_id)


@router.get("/sessions/{session_id}/turns", response_model=list[TurnRecord], tags=["sessions"])
async def sessions_turns(request: Request, session_id: int) -> Any:
    return await _ctx(request).sessions.load_turns(session_id)


@router.get("/sessions/{session_id}/status", response_model=SessionStatus | None, tags=["sessions"])
async def sessions_status(request: Request, session_id: int) -> Any:
    return await _ctx(request).sessions.status(session_id)


# ==================================================================
# 错题与趋势
# ==================================================================


@router.get("/mistakes", response_model=list[StoredMistake], tags=["reviews"])
async def mistakes_list(
    request: Request,
    include_mastered: bool = False,
    topic: str = "",
    limit: int = Query(default=200, ge=1, le=500),
) -> Any:
    return await _ctx(request).reviews.list_mistakes(
        include_mastered=include_mastered, topic=topic, limit=limit
    )


@router.get("/mistakes/counts", response_model=MistakeCounts, tags=["reviews"])
async def mistakes_counts(request: Request) -> MistakeCounts:
    pending, mastered = await _ctx(request).reviews.mistake_counts()
    return MistakeCounts(pending=pending, mastered=mastered)


@router.get("/mistakes/topics", tags=["reviews"])
async def mistakes_topics(request: Request) -> list[str]:
    return await _ctx(request).reviews.topics()


@router.post("/mistakes/mastered", response_model=Ok, tags=["reviews"])
async def mistakes_set_mastered(request: Request, body: SetMasteredBody) -> Ok:
    await _ctx(request).reviews.set_mastered(body.mistake_id, body.mastered)
    return Ok()


@router.delete("/mistakes/{mistake_id}", response_model=Ok, tags=["reviews"])
async def mistakes_delete(request: Request, mistake_id: int) -> Ok:
    await _ctx(request).reviews.delete_mistake(mistake_id)
    return Ok()


@router.get("/trends/overall", response_model=list[TrendPoint], tags=["reviews"])
async def trends_overall(request: Request, limit: int = Query(default=20, ge=1, le=100)) -> Any:
    return await _ctx(request).reviews.overall_series(limit=limit)


@router.get(
    "/trends/dimensions",
    response_model=dict[ScoreDimension, list[TrendPoint]],
    tags=["reviews"],
)
async def trends_dimensions(request: Request, limit: int = Query(default=20, ge=1, le=100)) -> Any:
    return await _ctx(request).reviews.dimension_series(limit=limit)


# ==================================================================
# 人设
# ==================================================================


@router.get("/personas", response_model=list[PersonaContract], tags=["personas"])
async def personas_list(request: Request) -> Any:
    return await _ctx(request).personas.list_all()


@router.post("/personas", response_model=PersonaContract, tags=["personas"])
async def personas_save(request: Request, contract: PersonaContract) -> Any:
    return await _ctx(request).personas.save(contract)


@router.delete("/personas/{persona_id}", response_model=Ok, tags=["personas"])
async def personas_delete(request: Request, persona_id: int) -> Ok:
    await _ctx(request).personas.delete(persona_id)
    return Ok()


@router.post("/personas/unique-name", tags=["personas"])
async def personas_unique_name(request: Request, body: UniqueNameBody) -> dict[str, str]:
    return {"name": await _ctx(request).personas.unique_name(body.base)}


# ==================================================================
# 资料库
# ==================================================================


@router.get("/library/resumes", response_model=list[StoredResume], tags=["library"])
async def library_resumes(request: Request, limit: int = Query(default=30, ge=1, le=200)) -> Any:
    return await _ctx(request).library.list_resumes(limit=limit)


@router.get("/library/jobs", response_model=list[StoredJob], tags=["library"])
async def library_jobs(request: Request, limit: int = Query(default=30, ge=1, le=200)) -> Any:
    return await _ctx(request).library.list_jobs(limit=limit)


# ==================================================================
# 配置与密钥
# ==================================================================


@router.get("/config", response_model=AppSettings, tags=["config"])
async def config_get(request: Request) -> Any:
    return _ctx(request).config.settings


@router.post("/config", response_model=Ok, tags=["config"])
async def config_save(request: Request, settings: AppSettings) -> Ok:
    ctx = _ctx(request)
    ctx.config.save(settings)
    await ctx.reload_models()
    return Ok()


@router.get("/config/keys/{provider_key}", tags=["config"])
async def config_key_present(request: Request, provider_key: str) -> dict[str, bool]:
    """只回报有没有配，绝不回传密钥本体。"""
    return {"present": bool(_ctx(request).config.get_api_key(provider_key))}


@router.post("/config/keys", response_model=Ok, tags=["config"])
async def config_set_key(request: Request, body: ApiKeyBody) -> Ok:
    _ctx(request).config.set_api_key(body.provider_key, body.api_key)
    await _ctx(request).reload_models()
    return Ok()


# ==================================================================
# 恢复
# ==================================================================


@router.post("/recovery/scan", response_model=list[InterruptedSession], tags=["recovery"])
async def recovery_scan(request: Request) -> Any:
    return await _ctx(request).recovery.scan()


# ==================================================================
# 异常出口
# ==================================================================


async def interviewer_error_handler(request: Request, exc: Exception) -> Any:
    from fastapi.responses import JSONResponse

    assert isinstance(exc, InterviewerError)
    logger.warning("接口返回业务错误 %s: %s", type(exc).__name__, exc.detail or exc.user_message)
    return JSONResponse(
        status_code=400,
        content={
            "kind": type(exc).__name__,
            "user_message": exc.user_message,
            "detail": exc.detail,
        },
    )
