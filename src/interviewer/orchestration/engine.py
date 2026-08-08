from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Coroutine
from typing import Any

from ..agents.director import Director
from ..agents.guard import Guard, repair_directive
from ..agents.live_agents import CodeExaminer, Copilot, StarAnalyst
from ..core.config import AppSettings, AudioSettings, ConfigStore
from ..core.errors import InterviewBusyError, InterviewerError, RealtimeError
from ..core.events import (
    AudioLevel,
    CopilotHint,
    DirectorDecided,
    DriftDetected,
    ElapsedTick,
    EngineFailure,
    EventBus,
    InterruptionFired,
    InterviewerSpeaking,
    LiveScoreUpdated,
    PhaseChanged,
    RealtimeStateChanged,
    ReanchorPerformed,
    SpeechActivity,
    StarProgress,
    TranscriptCommitted,
    TranscriptDelta,
)
from ..core.providers_catalog import RealtimeProvider
from ..core.types import InterviewPhase, ScoreDimension, SessionStatus, Speaker, TurnIntent
from ..data.repositories.session_repo import SessionRepository
from ..domain.interview import InterviewState
from ..domain.turn_plan import DirectorDecision, TurnPlan
from ..llm.router import ROLE_ASSIST, LLMRouter
from ..realtime.client import RealtimeClient
from ..realtime.recorder import SessionRecorder
from . import anchor, policy

logger = logging.getLogger(__name__)

_TICK_INTERVAL = 0.1
_MIN_ANSWER_CHARS = 2
# 面试官说完后候选人的沉默处理：先给提词，再由面试官轻推
_COPILOT_SILENCE = 6.5
_NUDGE_SILENCE = 15.0


class InterviewEngine:
    """双环编排。Fast Loop 是语音链路，Slow Loop 是这里的导演与状态机。"""

    def __init__(
        self,
        *,
        bus: EventBus,
        router: LLMRouter,
        store: ConfigStore,
        sessions: SessionRepository,
    ) -> None:
        self._bus = bus
        self._router = router
        self._store = store
        self._sessions = sessions

        self._director = Director(router)
        self._guard = Guard(router)
        self._star = StarAnalyst(router)
        self._copilot = Copilot(router)
        self._code = CodeExaminer(router)

        self._state: InterviewState | None = None
        self._client: RealtimeClient | None = None
        self._recorder: SessionRecorder | None = None

        self._started_at = 0.0
        self._closing = False
        self._close_triggered = False
        self._turn_ready = asyncio.Event()
        self._finished = asyncio.Event()

        self._pending_answer: list[str] = []
        self._answer_started_ms = 0
        self._candidate_speaking = False
        self._speech_started_ms = 0
        self._interviewer_voicing = False

        self._turn_timer: asyncio.Task[None] | None = None
        self._verbosity_timer: asyncio.Task[None] | None = None
        self._silence_timer: asyncio.Task[None] | None = None
        self._advance_task: asyncio.Task[None] | None = None
        self._tick_task: asyncio.Task[None] | None = None
        self._side_tasks: set[asyncio.Task[None]] = set()
        self._turn_lock = asyncio.Lock()
        self._star_hint = ""

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    @property
    def state(self) -> InterviewState | None:
        return self._state

    @property
    def running(self) -> bool:
        return self._state is not None and not self._closing

    async def start(self, state: InterviewState) -> None:
        if self._state is not None:
            raise InterviewBusyError()

        settings = self._store.settings
        catalog = settings.realtime.catalog()
        api_key = self._store.require_api_key(catalog.credential_key)

        self._state = state
        self._closing = False
        self._close_triggered = False
        self._finished.clear()
        self._started_at = time.monotonic()
        state.enter_phase(InterviewPhase.WARMUP)
        try:
            await self._boot(state, settings, catalog, api_key)
        except Exception:
            # 起不来就必须把占位彻底还回去。否则引擎永久停在「有面试在进行中」，
            # 之后每次点开始面试都只会撞上那句错误，而题库还会被重新生成一遍。
            await self._rollback_start(state)
            raise

    async def _boot(
        self,
        state: InterviewState,
        settings: AppSettings,
        catalog: RealtimeProvider,
        api_key: str,
    ) -> None:
        realtime_cfg = settings.realtime
        if settings.features.save_audio:
            self._recorder = SessionRecorder(
                state.session_id,
                candidate_rate=catalog.input_sample_rate,
                interviewer_rate=catalog.output_sample_rate,
            )

        voice = state.persona.voice or realtime_cfg.resolved_voice()
        self._client = RealtimeClient(
            provider=catalog,
            model=realtime_cfg.resolved_model(),
            voice=voice,
            api_key=api_key,
            temperature=realtime_cfg.temperature,
            audio=settings.audio,
            sink=self,
            clock=self._clock,
            loop=asyncio.get_running_loop(),
        )

        await self._sessions.set_status(state.session_id, SessionStatus.RUNNING)
        await self._client.connect(anchor.build_instructions(state))

        self._advance_task = asyncio.create_task(self._advance_loop(), name="engine-advance")
        self._tick_task = asyncio.create_task(self._tick_loop(), name="engine-tick")

        self._warn_audio_config(settings.audio)
        self._bus.emit(PhaseChanged(phase=state.phase, reason="面试开始"))
        await self._client.send_directive(anchor.opening_directive(state.persona))
        logger.info("面试开始 session=%s persona=%s", state.session_id, state.persona.name)

    async def _rollback_start(self, state: InterviewState) -> None:
        """把 start 已经做出的副作用逐项撤销，让引擎回到可再次开始的空闲态。"""
        for task in (self._advance_task, self._tick_task):
            if task is None:
                continue
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        self._advance_task = None
        self._tick_task = None

        for task in list(self._side_tasks):
            task.cancel()
        self._side_tasks.clear()

        if self._client is not None:
            with contextlib.suppress(Exception):
                await self._client.close("启动失败")
            self._client = None
        self._recorder = None

        with contextlib.suppress(Exception):
            await self._sessions.set_status(state.session_id, SessionStatus.DRAFT)
        self._state = None
        logger.warning("面试启动失败，已回滚 session=%s", state.session_id)

    def _remember_gain(self, gain: float) -> None:
        """记住这台机器的麦克风增益，下次开场不用再爬坡。"""
        settings = self._store.settings
        if abs(gain - settings.audio.learned_gain) < 0.15:
            return
        try:
            settings.audio.learned_gain = round(min(8.0, max(0.5, gain)), 2)
            self._store.save(settings)
            logger.info("已记住麦克风增益 %.2fx", settings.audio.learned_gain)
        except Exception:
            logger.warning("保存麦克风增益失败", exc_info=True)

    def _warn_audio_config(self, audio: AudioSettings) -> None:
        """阈值偏高会让服务端听不到说话，而已保存的旧配置不会因为改默认值而更新。"""
        if audio.vad_threshold > 0.35:
            logger.warning("人声灵敏度偏高：%.2f，服务端可能判定为静音", audio.vad_threshold)
            self._bus.emit(
                EngineFailure(
                    user_message=(
                        f"人声灵敏度当前 {audio.vad_threshold:.2f} 偏高，"
                        "若面试官听不到你说话，去「设置 → 音频」调到 0.30 以下"
                    ),
                    fatal=False,
                )
            )


    async def stop(self, *, aborted: bool = False) -> InterviewState | None:
        state = self._state
        if state is None or self._closing:
            return state
        self._closing = True

        self._cancel_turn_timer()
        self._cancel_verbosity_timer()
        self._cancel_silence_timer()

        # 收尾与致命错误都是从 _side_tasks 里的任务调进来的，
        # 取消自己会让后续落库与 _finished 全部跳过，必须排除当前任务。
        current = asyncio.current_task()
        doomed = [
            task
            for task in (self._advance_task, self._tick_task, *self._side_tasks)
            if task is not None and task is not current
        ]
        for task in doomed:
            task.cancel()
        self._turn_ready.set()

        for task in doomed:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        self._side_tasks = {t for t in self._side_tasks if t is current}
        self._advance_task = None
        self._tick_task = None

        state.elapsed_ms = self._clock()
        if self._client is not None:
            self._remember_gain(self._client.capture.auto_gain_factor)
            await self._client.close("面试结束")
            self._client = None

        audio_path = ""
        if self._recorder is not None:
            saved = self._recorder.finalize()
            audio_path = str(saved) if saved else ""
            self._recorder = None

        await self._sessions.sync_records(state)
        await self._sessions.persist_state(state)
        await self._sessions.finish(state.session_id, duration_ms=state.elapsed_ms, audio_path=audio_path)
        await self._sessions.set_status(
            state.session_id, SessionStatus.ABORTED if aborted else SessionStatus.REVIEWING
        )

        self._state = None
        self._finished.set()
        logger.info("面试结束 session=%s 时长=%dms", state.session_id, state.elapsed_ms)
        return state

    async def wait_finished(self) -> None:
        await self._finished.wait()

    def _clock(self) -> int:
        if self._started_at <= 0.0:
            return 0
        return int((time.monotonic() - self._started_at) * 1000)

    # ------------------------------------------------------------------
    # RealtimeSink 实现
    # ------------------------------------------------------------------

    def on_state(self, connected: bool, reason: str) -> None:
        self._bus.emit(RealtimeStateChanged(connected=connected, reason=reason))

    def on_candidate_speech(self, speaking: bool) -> None:
        self._candidate_speaking = speaking
        self._bus.emit(SpeechActivity(speaking=speaking))
        if speaking:
            self._speech_started_ms = self._clock()
            if not self._pending_answer:
                self._answer_started_ms = self._speech_started_ms
            self._cancel_turn_timer()
            self._cancel_silence_timer()
            self._start_verbosity_timer()
        else:
            self._cancel_verbosity_timer()

    def on_candidate_text(
        self, text: str, *, final: bool, started_at_ms: int = 0, duration_ms: int = 0
    ) -> None:
        if not final:
            self._bus.emit(TranscriptDelta(speaker=Speaker.CANDIDATE.value, text=text))
            return
        state = self._state
        if state is None or len(text.strip()) < _MIN_ANSWER_CHARS:
            return
        turn = state.append_turn(
            speaker=Speaker.CANDIDATE,
            text=text,
            started_at_ms=started_at_ms or self._answer_started_ms,
            duration_ms=duration_ms,
        )
        self._pending_answer.append(text)
        self._bus.emit(
            TranscriptCommitted(
                turn_id=turn.index,
                speaker=Speaker.CANDIDATE.value,
                text=text,
                started_at_ms=turn.started_at_ms,
                duration_ms=turn.duration_ms,
            )
        )
        self._spawn(self._persist_turn(state, turn.index))
        self._schedule_turn()

    def on_interviewer_text(
        self, text: str, *, final: bool, started_at_ms: int = 0, duration_ms: int = 0
    ) -> None:
        if not final:
            self._bus.emit(TranscriptDelta(speaker=Speaker.INTERVIEWER.value, text=text))
            return
        state = self._state
        if state is None:
            return
        current = state.current_question
        turn = state.append_turn(
            speaker=Speaker.INTERVIEWER,
            text=text,
            started_at_ms=started_at_ms,
            duration_ms=duration_ms,
            intent=current.intent if current else None,
        )
        self._bus.emit(
            TranscriptCommitted(
                turn_id=turn.index,
                speaker=Speaker.INTERVIEWER.value,
                text=text,
                started_at_ms=turn.started_at_ms,
                duration_ms=turn.duration_ms,
            )
        )
        self._spawn(self._persist_turn(state, turn.index))
        self._spawn(self._guard_check(text))

    def on_candidate_audio(self, pcm: bytes, elapsed_ms: int) -> None:
        if self._recorder is not None:
            self._recorder.write_candidate(elapsed_ms, pcm)

    def on_interviewer_audio(self, pcm: bytes, elapsed_ms: int) -> None:
        if self._recorder is not None:
            self._recorder.write_interviewer(elapsed_ms, pcm)

    def on_response(self, active: bool) -> None:
        if active:
            self._cancel_turn_timer()
            self._cancel_silence_timer()
        else:
            self._start_silence_timer()

    def on_barge_in(self) -> None:
        self._bus.emit(InterruptionFired(by_interviewer=False, reason="你打断了面试官"))

    def on_unauthorized_response(self) -> None:
        logger.info("已拦截一次未授权发言")

    def on_error(self, message: str, *, fatal: bool) -> None:
        self._bus.emit(EngineFailure(user_message=message, fatal=fatal))
        if fatal:
            self._spawn(self._abort_on_fatal())

    async def _abort_on_fatal(self) -> None:
        await asyncio.sleep(0)
        await self.stop(aborted=True)

    # ------------------------------------------------------------------
    # 回合边界
    # ------------------------------------------------------------------

    def _schedule_turn(self) -> None:
        self._cancel_turn_timer()
        gap = self._store.settings.orchestration.turn_gap_ms / 1000
        self._turn_timer = asyncio.create_task(self._turn_timeout(gap), name="engine-turn-gap")

    async def _turn_timeout(self, delay: float) -> None:
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return
        if self._candidate_speaking or self._closing:
            return
        self._turn_ready.set()

    def _cancel_turn_timer(self) -> None:
        timer, self._turn_timer = self._turn_timer, None
        if timer is not None:
            timer.cancel()

    def _start_verbosity_timer(self) -> None:
        state = self._state
        if state is None:
            return
        settings = self._store.settings.orchestration
        if not state.can_interrupt(settings.interrupt_budget_per_phase):
            return
        threshold = policy.interrupt_threshold_ms(state, settings) / 1000
        self._cancel_verbosity_timer()
        self._verbosity_timer = asyncio.create_task(
            self._verbosity_timeout(threshold), name="engine-verbosity"
        )

    async def _verbosity_timeout(self, delay: float) -> None:
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return
        if not self._candidate_speaking or self._closing:
            return
        await self._interrupt_now("你说得太久还没落到重点")

    def _cancel_verbosity_timer(self) -> None:
        timer, self._verbosity_timer = self._verbosity_timer, None
        if timer is not None:
            timer.cancel()

    def _start_silence_timer(self) -> None:
        state = self._state
        if state is None or state.phase is InterviewPhase.CLOSING:
            return
        self._cancel_silence_timer()
        self._silence_timer = asyncio.create_task(self._silence_watch(), name="engine-silence")

    async def _silence_watch(self) -> None:
        """候选人迟迟不开口：先自动给提词，再让面试官轻推一句。"""
        try:
            await asyncio.sleep(_COPILOT_SILENCE)
            if self._candidate_speaking or self._closing:
                return
            if self._store.settings.features.copilot_enabled:
                with contextlib.suppress(Exception):
                    await self.request_hint(auto=True)
            await asyncio.sleep(_NUDGE_SILENCE - _COPILOT_SILENCE)
            if self._candidate_speaking or self._closing:
                return
            await self._nudge()
        except asyncio.CancelledError:
            return

    async def _nudge(self) -> None:
        client = self._client
        if client is None or client.is_responding:
            return
        with contextlib.suppress(Exception):
            await client.send_directive(anchor.nudge_directive())

    def _cancel_silence_timer(self) -> None:
        timer, self._silence_timer = self._silence_timer, None
        if timer is not None:
            timer.cancel()

    async def _interrupt_now(self, reason: str) -> None:
        """面试官主动插话。打断不需要新的内容决策，直接从状态拼指令，零额外延迟。"""
        state = self._state
        client = self._client
        if state is None or client is None:
            return
        current = state.current_question
        focus = current.brief if current else "刚才的问题"
        directive = anchor.directive_message(
            intent=TurnIntent.INTERRUPT,
            brief=f"他已经说了很久还没讲到重点。打断他，要求他直接回答：{focus}",
        )
        state.interrupts_used_in_phase += 1
        marked = state.last_candidate_turn()
        if marked is not None:
            marked.was_interrupted = True
        await client.barge_in(directive)
        self._bus.emit(InterruptionFired(by_interviewer=True, reason=reason))
        logger.info("面试官主动打断：%s", reason)

    # ------------------------------------------------------------------
    # 主推进循环
    # ------------------------------------------------------------------

    async def _advance_loop(self) -> None:
        while not self._closing:
            await self._turn_ready.wait()
            self._turn_ready.clear()
            if self._closing:
                return
            try:
                async with self._turn_lock:
                    await self._run_turn()
            except asyncio.CancelledError:
                raise
            except InterviewerError as exc:
                logger.warning("回合推进失败: %s", exc)
                self._bus.emit(EngineFailure(user_message=exc.user_message, detail=exc.detail))
                await self._recover_turn()
            except Exception as exc:
                logger.exception("回合推进异常")
                self._bus.emit(EngineFailure(user_message="面试推进出现异常", detail=str(exc)))
                await self._recover_turn()

    async def _run_turn(self) -> None:
        state = self._state
        client = self._client
        if state is None or client is None:
            return
        state.elapsed_ms = self._clock()

        answer = " ".join(self._pending_answer).strip()

        if state.phase is InterviewPhase.CANDIDATE_QA and answer:
            self._pending_answer.clear()
            await self._answer_candidate_question(client, answer)
            return

        plan = policy.plan_turn(state, self._store.settings.orchestration)
        decision = await self._decide(state, plan)
        # 决策成功才消费缓冲：导演超时或抛错时这段回答要留给下一轮，不能丢
        self._pending_answer.clear()
        action = state.observe_answer(decision.answer_quality)
        decision = policy.enforce_depth_action(state, decision, action)

        for skill in decision.covered_skills:
            state.mark_skill_touched(skill)
        if decision.dimension_deltas:
            state.blend_scores(decision.dimension_deltas)
            self._bus.emit(LiveScoreUpdated(scores=dict(state.live_scores)))

        if decision.intent is TurnIntent.CLOSE:
            await self._close_interview(client, state, decision)
            return

        await self._apply_phase_change(state, decision, plan)

        star_hint = ""
        if decision.intent is TurnIntent.STAR_PROBE:
            star_hint = self._star_hint
        elif decision.is_personality:
            star_hint = "这是一个性格/价值观问题，语气可以缓一点，但仍要问得具体。"

        state.open_question(
            intent=decision.intent,
            brief=decision.brief,
            target_skill=decision.target_skill,
            domain=decision.domain,
            depth=decision.depth,
            bank_question_id=decision.chosen_question.id if decision.chosen_question else None,
            is_personality=decision.is_personality,
        )
        self._bus.emit(
            DirectorDecided(
                intent=decision.intent,
                brief=decision.brief,
                target_skill=decision.target_skill,
                follow_up_depth=state.follow_up_depth,
            )
        )

        await self._maybe_reanchor(state, client, trigger="周期重锚")
        await client.send_directive(
            anchor.directive_message(
                intent=decision.intent,
                brief=decision.brief,
                star_hint=star_hint,
            )
        )

        if answer:
            self._spawn(self._star_check(state, answer))
        await self._sessions.persist_state(state)

    async def _decide(self, state: InterviewState, plan: TurnPlan) -> DirectorDecision:
        timeout = self._store.settings.orchestration.director_timeout_ms / 1000
        return await asyncio.wait_for(self._director.decide(state, plan), timeout=timeout)

    async def _answer_candidate_question(self, client: RealtimeClient, question: str) -> None:
        state = self._state
        if state is None:
            return
        await client.send_directive(anchor.candidate_question_directive(question))
        await self._sessions.persist_state(state)

    async def _apply_phase_change(
        self, state: InterviewState, decision: DirectorDecision, plan: TurnPlan
    ) -> None:
        target = policy.resolve_phase_transition(state)
        if target is None and decision.should_advance_phase and not plan.must_close:
            nxt = state.next_phase()
            target = nxt if nxt is not state.phase else None
        if target is None:
            return
        if target is InterviewPhase.FINISHED:
            target = InterviewPhase.CLOSING
        reason = "时间到收尾线" if state.must_close() else "本环节已完成"
        state.enter_phase(target)
        self._bus.emit(PhaseChanged(phase=target, reason=reason))
        await self._maybe_reanchor(state, self._client, trigger=f"进入{target.label}", force=True)

    async def _close_interview(
        self, client: RealtimeClient, state: InterviewState, decision: DirectorDecision
    ) -> None:
        if state.phase is not InterviewPhase.CLOSING:
            state.enter_phase(InterviewPhase.CLOSING)
            self._bus.emit(PhaseChanged(phase=InterviewPhase.CLOSING, reason="进入收尾"))
        state.open_question(
            intent=TurnIntent.CLOSE,
            brief=decision.brief,
            target_skill="",
        )
        await client.send_directive(
            anchor.directive_message(intent=TurnIntent.CLOSE, brief=decision.brief)
        )
        await self._sessions.persist_state(state)
        self._spawn(self._finish_after_closing())

    async def _finish_after_closing(self) -> None:
        client = self._client
        if client is None:
            return
        # 等收尾话说完再断链，避免最后一句被截断
        for _ in range(120):
            await asyncio.sleep(0.25)
            if self._closing:
                return
            if not client.is_responding and client.player.pending_ms <= 0:
                break
        await self.stop()

    async def _recover_turn(self) -> None:
        """一轮失败不能让面试卡死，重锚后让面试官把话语权交回候选人。"""
        state = self._state
        client = self._client
        if state is None or client is None:
            return
        with contextlib.suppress(Exception):
            await self._maybe_reanchor(state, client, trigger="异常恢复", force=True)
            await client.send_directive(
                anchor.directive_message(
                    intent=TurnIntent.ACKNOWLEDGE,
                    brief="用一句极短的话让候选人继续把刚才的回答说完",
                )
            )

    # ------------------------------------------------------------------
    # 重锚与守卫
    # ------------------------------------------------------------------

    async def _maybe_reanchor(
        self,
        state: InterviewState,
        client: RealtimeClient | None,
        *,
        trigger: str,
        force: bool = False,
    ) -> None:
        if client is None:
            return
        every = self._store.settings.orchestration.reanchor_every_turns
        if not force and not state.needs_reanchor(every):
            return
        await client.reanchor(anchor.build_instructions(state))
        state.note_reanchor()
        self._bus.emit(ReanchorPerformed(turn_index=state.turn_index, trigger=trigger))
        logger.info("已重锚人格 turn=%d trigger=%s", state.turn_index, trigger)

    async def _guard_check(self, spoken: str) -> None:
        state = self._state
        client = self._client
        if state is None or client is None:
            return
        timeout = self._store.settings.orchestration.guard_timeout_ms
        verdict = await self._guard.inspect(spoken, state.persona, timeout_ms=timeout)
        if not verdict.violated:
            return
        state.register_drift(verdict.kind)
        repaired = False
        with contextlib.suppress(Exception):
            await client.cancel_current_response()
            await client.reanchor(anchor.build_instructions(state))
            await client.send_directive(repair_directive(verdict, state.persona))
            state.note_reanchor()
            repaired = True
        self._bus.emit(
            DriftDetected(kind=verdict.kind, excerpt=verdict.excerpt, repaired=repaired)
        )
        logger.warning("人格漂移已处理 kind=%s repaired=%s", verdict.kind.value, repaired)

    async def _star_check(self, state: InterviewState, answer: str) -> None:
        if not state.star.is_behavioral:
            return
        current = state.current_question
        question = current.spoken_text or current.brief if current else ""
        verdict = await self._star.analyze(question=question, answer=answer)
        if verdict is None:
            return
        state.star.present = verdict.present
        self._star_hint = verdict.probe_hint
        self._bus.emit(
            StarProgress(
                present=set(verdict.present),
                missing=set(state.star.missing),
                is_behavioral=True,
            )
        )

    # ------------------------------------------------------------------
    # 用户交互
    # ------------------------------------------------------------------

    async def request_hint(self, *, auto: bool = False) -> None:
        """auto=True 时由沉默监视器触发，用户并没点提词，失败就静默跳过。"""
        state = self._state
        if state is None:
            return
        current = state.current_question
        question = (current.spoken_text or current.brief) if current else ""
        partial = " ".join(self._pending_answer).strip()
        payload = await self._copilot.hint(
            question=question,
            partial_answer=partial,
            resume_digest=state.resume_digest,
        )
        if payload.is_empty:
            if not auto:
                model = self._store.settings.chat_model(ROLE_ASSIST)
                self._bus.emit(
                    EngineFailure(
                        user_message=f"提词器（{model}）没能及时返回，可能网络慢或模型繁忙，稍后再试"
                    )
                )
            return
        self._bus.emit(
            CopilotHint(
                keywords=payload.keywords,
                outline=payload.outline,
                caution=payload.caution,
            )
        )

    async def submit_code(self, language: str, source: str) -> None:
        state = self._state
        client = self._client
        if state is None or client is None:
            return
        state.code_language = language
        state.code_snapshot = source
        current = state.current_question
        problem = (current.spoken_text or current.brief) if current else ""
        probe = await self._code.probe(language=language, source=source, problem=problem)
        if probe is None:
            self._bus.emit(EngineFailure(user_message="代码分析超时，面试官这次先不追问"))
            return
        if current is not None:
            current.quality = probe.quality
        state.blend_scores({ScoreDimension.CODING: probe.quality * 100})
        self._bus.emit(LiveScoreUpdated(scores=dict(state.live_scores)))
        await client.send_directive(
            anchor.code_review_directive(
                probe=probe.probe, complexity=probe.complexity, issues=probe.issues
            )
        )
        await self._sessions.persist_state(state)

    async def interrupt_interviewer(self) -> None:
        client = self._client
        if client is None:
            return
        await client.cancel_current_response()
        self._bus.emit(InterruptionFired(by_interviewer=False, reason="你打断了面试官"))

    async def finish_early(self) -> None:
        state = self._state
        client = self._client
        if state is None or client is None:
            return
        state.enter_phase(InterviewPhase.CLOSING)
        self._bus.emit(PhaseChanged(phase=InterviewPhase.CLOSING, reason="提前结束"))
        await self._maybe_reanchor(state, client, trigger="提前收尾", force=True)
        await client.send_directive(
            anchor.directive_message(
                intent=TurnIntent.CLOSE, brief="时间关系，今天先聊到这里，向候选人说明后续流程"
            )
        )
        self._spawn(self._finish_after_closing())

    def set_muted(self, muted: bool) -> None:
        if self._client is not None:
            self._client.capture.set_muted(muted)

    # ------------------------------------------------------------------
    # 后台
    # ------------------------------------------------------------------

    async def _tick_loop(self) -> None:
        while not self._closing:
            await asyncio.sleep(_TICK_INTERVAL)
            state = self._state
            client = self._client
            if state is None:
                continue
            state.elapsed_ms = self._clock()
            self._bus.emit(
                ElapsedTick(elapsed_ms=state.elapsed_ms, remaining_ms=state.remaining_ms)
            )
            if client is not None:
                self._bus.emit(
                    AudioLevel(
                        candidate=client.capture.level,
                        interviewer=client.player.level,
                    )
                )
                speaking = client.is_responding or client.player.pending_ms > 0
                if speaking != self._interviewer_voicing:
                    self._interviewer_voicing = speaking
                    self._bus.emit(InterviewerSpeaking(speaking=speaking))
            # 只触发一次：tick 每 100ms 一跳，反复置位会排出几十次多余的导演调用
            if not self._close_triggered and state.must_close() and state.phase is not InterviewPhase.CLOSING:
                self._close_triggered = True
                self._turn_ready.set()

    async def _persist_turn(self, state: InterviewState, turn_index: int) -> None:
        turn = next((t for t in state.turns if t.index == turn_index), None)
        if turn is None:
            return
        await self._sessions.upsert_turn(state.session_id, turn)
        question = state.current_question
        if question is not None:
            await self._sessions.upsert_question(state.session_id, question)

    def _spawn(self, coro: Coroutine[Any, Any, None]) -> None:
        task = asyncio.create_task(coro)
        self._side_tasks.add(task)
        task.add_done_callback(self._side_tasks.discard)
        task.add_done_callback(_log_task_failure)


def _log_task_failure(task: asyncio.Task[None]) -> None:
    if task.cancelled():
        return
    error = task.exception()
    if error is not None and not isinstance(error, RealtimeError):
        logger.error("后台任务失败", exc_info=error)
