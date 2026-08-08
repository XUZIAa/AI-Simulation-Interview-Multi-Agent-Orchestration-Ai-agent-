from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlencode

import websockets
from websockets.asyncio.client import ClientConnection, connect

from ..core.config import AudioSettings
from ..core.errors import RealtimeClosedError, RealtimeError
from ..core.providers_catalog import RealtimeProvider
from . import protocol as proto
from .audio_io import AudioCapture, AudioPlayer
from .echo_gate import EchoGate

logger = logging.getLogger(__name__)

_MAX_MESSAGE = 24 * 1024 * 1024
_STATS_INTERVAL = 5.0
_BARGE_IN_GRACE_MS = 1000  # 面试官开口后的免打断窗口


@dataclass
class _LinkStats:
    """上下行链路计数，用于定位「说话没反应」卡在哪一环。"""

    sent: int = 0
    gated: int = 0
    peak: float = 0.0
    speech_started: int = 0
    speech_stopped: int = 0
    transcripts: int = 0
    audio_out: int = 0
    echo_events: int = 0
    grace_skips: int = 0

    def reset(self) -> None:
        self.sent = 0
        self.gated = 0
        self.peak = 0.0
        self.speech_started = 0
        self.speech_stopped = 0
        self.transcripts = 0
        self.audio_out = 0
        self.echo_events = 0
        self.grace_skips = 0


class RealtimeSink(Protocol):
    """编排层需要实现的回调集合。realtime 层只负责音频与协议，不做任何决策。"""

    def on_state(self, connected: bool, reason: str) -> None: ...

    def on_candidate_speech(self, speaking: bool) -> None: ...

    def on_candidate_text(
        self, text: str, *, final: bool, started_at_ms: int = 0, duration_ms: int = 0
    ) -> None: ...

    def on_interviewer_text(
        self, text: str, *, final: bool, started_at_ms: int = 0, duration_ms: int = 0
    ) -> None: ...

    def on_candidate_audio(self, pcm: bytes, elapsed_ms: int) -> None: ...

    def on_interviewer_audio(self, pcm: bytes, elapsed_ms: int) -> None: ...

    def on_response(self, active: bool) -> None: ...

    def on_barge_in(self) -> None: ...

    def on_unauthorized_response(self) -> None: ...

    def on_error(self, message: str, *, fatal: bool) -> None: ...


class RealtimeClient:
    """端到端语音会话。持有采集、播放与回声门控，构成完整的全双工闭环。"""

    def __init__(
        self,
        *,
        provider: RealtimeProvider,
        model: str,
        voice: str,
        api_key: str,
        temperature: float,
        audio: AudioSettings,
        sink: RealtimeSink,
        clock: Callable[[], int],
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        self._provider = provider
        self._model = model
        self._voice = voice
        self._api_key = api_key
        self._temperature = temperature
        self._audio_settings = audio
        self._sink = sink
        self._clock = clock

        self._capture = AudioCapture(
            sample_rate=provider.input_sample_rate,
            loop=loop,
            device_name=audio.input_device,
            gain=audio.input_gain,
            auto_gain=audio.auto_gain,
            initial_agc=audio.learned_gain,
        )
        prefill = max(200, audio.playback_buffer_ms)
        self._player = AudioPlayer(
            sample_rate=provider.output_sample_rate,
            device_name=audio.output_device,
            prefill_ms=prefill,
            refill_ms=max(120, prefill // 2),
        )
        self._echo_gate = EchoGate(
            self._player,
            capture_rate=provider.input_sample_rate,
            player_rate=provider.output_sample_rate,
        )
        self._stats = _LinkStats()

        self._ws: ClientConnection | None = None
        self._tasks: list[asyncio.Task[None]] = []
        self._instructions = ""
        self._responding = False
        self._response_id: str | None = None
        self._closing = False
        self._authorized = False

        self._candidate_start_ms = 0
        self._candidate_buffer = ""
        self._interviewer_start_ms = 0
        self._interviewer_buffer = ""
        self._response_start_ms = 0
        self._response_chunks = 0
        self._response_chars = 0

    # ---------- 状态 ----------

    @property
    def connected(self) -> bool:
        return self._ws is not None and not self._closing

    @property
    def is_responding(self) -> bool:
        return self._responding

    @property
    def capture(self) -> AudioCapture:
        return self._capture

    @property
    def player(self) -> AudioPlayer:
        return self._player

    @property
    def echo_gate(self) -> EchoGate:
        return self._echo_gate

    # ---------- 生命周期 ----------

    async def connect(self, instructions: str) -> None:
        if self._ws is not None:
            raise RealtimeError("实时会话已建立")
        self._instructions = instructions
        url = f"{self._provider.ws_url}?{urlencode({'model': self._model})}"
        try:
            self._ws = await connect(
                url,
                additional_headers={"Authorization": f"Bearer {self._api_key}"},
                max_size=_MAX_MESSAGE,
                ping_interval=20,
                ping_timeout=20,
                open_timeout=20,
            )
        except (OSError, websockets.exceptions.WebSocketException, TimeoutError) as exc:
            raise RealtimeError(f"连接实时语音服务失败: {exc}") from exc

        await self._send(self._build_session_update())
        self._player.start()
        self._capture.start()
        self._tasks = [
            asyncio.create_task(self._recv_loop(), name="realtime-recv"),
            asyncio.create_task(self._send_loop(), name="realtime-send"),
            asyncio.create_task(self._stats_loop(), name="realtime-stats"),
        ]
        self._sink.on_state(True, "")
        logger.info("实时会话建立 model=%s voice=%s", self._model, self._voice)

    async def close(self, reason: str = "") -> None:
        if self._closing:
            return
        self._closing = True
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        self._tasks.clear()
        self._capture.stop()
        self._player.stop()
        ws, self._ws = self._ws, None
        if ws is not None:
            with contextlib.suppress(Exception):
                await ws.close()
        self._sink.on_state(False, reason)
        logger.info("实时会话关闭 reason=%s", reason or "正常结束")

    # ---------- 对外操作 ----------

    def _build_session_update(self) -> dict[str, Any]:
        audio = self._audio_settings
        return proto.session_update(
            instructions=self._instructions,
            voice=self._voice,
            audio_format=self._provider.audio_format,
            temperature=self._temperature,
            semantic_vad=audio.semantic_vad and self._provider.supports_semantic_vad,
            vad_threshold=audio.vad_threshold,
            silence_duration_ms=audio.silence_duration_ms,
            prefix_padding_ms=audio.prefix_padding_ms,
        )

    async def reanchor(self, instructions: str) -> None:
        """重发人格锚点。模型的音频历史会滚动丢弃，身份必须周期性重灌。"""
        self._instructions = instructions
        await self._send(self._build_session_update())

    async def send_directive(self, text: str, *, request_response: bool = True) -> None:
        """下发导演指令。只有这条路径能授予发言权。"""
        await self._send(proto.system_note(text))
        if request_response:
            # 先把残留的输入音频清掉，服务端才会立刻着手这次响应而不是继续等输入
            await self._send(proto.audio_clear())
            self._authorized = True
            await self._send(proto.response_create())

    async def barge_in(self, directive: str) -> None:
        """面试官主动插话：先掐掉可能在播的音频，再立刻要求生成。"""
        if self._responding:
            await self._cancel_response()
        self._player.clear()
        await self.send_directive(directive, request_response=True)

    async def cancel_current_response(self) -> None:
        if self._responding:
            await self._cancel_response()
        self._player.clear()

    async def _cancel_response(self) -> None:
        """取消当前正在生成的响应。

        注意不能清 _authorized：那是给下一次 response.create 的许可，
        若被这里撕掉，服务端随后创建的响应会被我们自己拦截，面试官就哑了。
        """
        await self._send(proto.response_cancel())
        self._responding = False
        self._response_id = None
        self._sink.on_response(False)

    async def _send(self, event: dict[str, Any]) -> None:
        ws = self._ws
        if ws is None:
            raise RealtimeClosedError("实时连接不可用")
        try:
            await ws.send(json.dumps(event, ensure_ascii=False))
        except websockets.exceptions.WebSocketException as exc:
            raise RealtimeClosedError(str(exc)) from exc

    # ---------- 上行 ----------

    async def _send_loop(self) -> None:
        try:
            while True:
                frame = await self._capture.read()
                self._stats.peak = max(self._stats.peak, self._capture.level)
                if self._echo_gate.is_echo(frame):
                    self._stats.gated += 1
                    continue
                self._stats.sent += 1
                self._sink.on_candidate_audio(frame, self._clock())
                await self._send(proto.audio_append(base64.b64encode(frame).decode("ascii")))
        except asyncio.CancelledError:
            raise
        except RealtimeClosedError:
            logger.info("上行循环结束：连接已关闭")
        except Exception as exc:
            logger.exception("上行循环异常")
            self._sink.on_error(f"音频上行中断: {exc}", fatal=True)

    async def _stats_loop(self) -> None:
        """周期性汇报链路状态。

        「说话没反应」可能卡在采集、门控、上行或服务端 VAD，
        没有这些数字只能靠猜。
        """
        while True:
            await asyncio.sleep(_STATS_INTERVAL)
            s = self._stats
            logger.info(
                "链路 %ds：上行 %d 帧(回声丢 %d) 电平 %.3f 增益 %.1fx"
                "｜服务端：语音 %d/%d 转写 %d｜面试官音频 %d 块"
                "｜回声误触发 %d 免打断跳过 %d",
                int(_STATS_INTERVAL),
                s.sent,
                s.gated,
                s.peak,
                self._capture.auto_gain_factor,
                s.speech_started,
                s.speech_stopped,
                s.transcripts,
                s.audio_out,
                s.echo_events,
                s.grace_skips,
            )
            if s.sent > 0 and s.speech_started == 0 and 0.02 < s.peak < 0.25:
                logger.warning(
                    "说话电平偏低（峰值 %.3f，增益已自动升到 %.1fx），服务端仍可能判定为静音",
                    s.peak,
                    self._capture.auto_gain_factor,
                )
            s.reset()

    # ---------- 下行 ----------

    async def _recv_loop(self) -> None:
        ws = self._ws
        if ws is None:
            return
        try:
            async for raw in ws:
                if isinstance(raw, bytes):
                    continue
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                await self._dispatch(event)
        except asyncio.CancelledError:
            raise
        except websockets.exceptions.ConnectionClosed as exc:
            if not self._closing:
                self._sink.on_error(f"实时连接断开: {exc.code}", fatal=True)
        except Exception as exc:
            logger.exception("下行循环异常")
            self._sink.on_error(f"实时链路异常: {exc}", fatal=True)

    async def _dispatch(self, event: dict[str, Any]) -> None:
        kind = event.get("type", "")

        if kind == proto.SPEECH_STARTED:
            self._stats.speech_started += 1
            # 面试官正在说话时，这个事件可能是扬声器回流触发的。
            # 若门控正在抑制回声，就不能当成真人插话去取消响应，
            # 否则面试官会被自己的声音打断，一句话都说不完。
            if self._responding and self._echo_gate.suppressing:
                self._stats.echo_events += 1
                return
            self._candidate_start_ms = self._clock()
            self._candidate_buffer = ""
            self._sink.on_candidate_speech(True)
            if self._responding:
                # 面试官刚开口的头一秒不让打断：真人也不会因为对方清嗓子就停下，
                # 而 VAD 对瞬时噪音很敏感，否则每句话都会被掐断
                if self._clock() - self._response_start_ms < _BARGE_IN_GRACE_MS:
                    self._stats.grace_skips += 1
                    return
                await self._cancel_response()
                self._sink.on_barge_in()
            else:
                self._player.clear()
            return

        if kind == proto.SPEECH_STOPPED:
            self._stats.speech_stopped += 1
            self._sink.on_candidate_speech(False)
            return

        if kind == proto.INPUT_TRANSCRIPT_DELTA:
            piece = event.get("delta") or event.get("text") or ""
            if piece:
                self._candidate_buffer += piece
                self._sink.on_candidate_text(piece, final=False)
            return

        if kind == proto.INPUT_TRANSCRIPT_DONE:
            text = (event.get("transcript") or self._candidate_buffer).strip()
            started = self._candidate_start_ms
            self._candidate_buffer = ""
            self._stats.transcripts += 1
            logger.info("候选人转写完成 %d 字: %s", len(text), text[:60] or "(空)")
            if text:
                self._sink.on_candidate_text(
                    text,
                    final=True,
                    started_at_ms=started,
                    duration_ms=max(0, self._clock() - started),
                )
            return

        if kind == proto.INPUT_TRANSCRIPT_FAILED:
            self._sink.on_error("语音识别失败，请确认麦克风输入正常", fatal=False)
            return

        if kind == proto.RESPONSE_CREATED:
            if not self._authorized:
                # 服务端在未获授权时自行开口，立刻收回，保证发言权只归导演
                logger.warning("拦截未授权的模型发言")
                self._player.clear()
                await self._cancel_response()
                self._sink.on_unauthorized_response()
                return
            self._authorized = False
            self._responding = True
            self._response_id = (event.get("response") or {}).get("id")
            self._response_start_ms = self._clock()
            self._response_chunks = 0
            self._response_chars = 0
            self._interviewer_start_ms = self._clock()
            self._interviewer_buffer = ""
            self._sink.on_response(True)
            return

        if kind == proto.RESPONSE_AUDIO_DELTA:
            chunk = event.get("delta")
            if chunk and self._responding:
                pcm = base64.b64decode(chunk)
                self._stats.audio_out += 1
                self._response_chunks += 1
                self._player.push(pcm)
                self._sink.on_interviewer_audio(pcm, self._clock())
            return

        if kind in (proto.RESPONSE_TRANSCRIPT_DELTA, proto.RESPONSE_TEXT_DELTA):
            piece = event.get("delta") or ""
            if piece and self._responding:
                self._interviewer_buffer += piece
                self._response_chars += len(piece)
                self._sink.on_interviewer_text(piece, final=False)
            return

        if kind in (proto.RESPONSE_TRANSCRIPT_DONE, proto.RESPONSE_TEXT_DONE):
            text = (event.get("transcript") or event.get("text") or self._interviewer_buffer).strip()
            if text and self._responding:
                self._sink.on_interviewer_text(
                    text,
                    final=True,
                    started_at_ms=self._interviewer_start_ms,
                    duration_ms=max(0, self._clock() - self._interviewer_start_ms),
                )
            self._interviewer_buffer = ""
            return

        if kind == proto.RESPONSE_DONE:
            self._responding = False
            self._response_id = None
            # 一句话只说了半截，可能是被打断、被 token 上限截断，也可能本来就说完了。
            # 三者的处理完全不同，必须把服务端给的结论原样记下来。
            body = event.get("response") or {}
            status = str(body.get("status") or "")
            details = body.get("status_details") or {}
            reason = str(details.get("reason") or details.get("type") or "")
            logger.info(
                "面试官发言结束 音频=%d 块 文本=%d 字 状态=%s%s",
                self._response_chunks,
                self._response_chars,
                status or "未报",
                f" 原因={reason}" if reason else "",
            )
            self._response_chunks = 0
            # 这一轮不会再有音频，让播放器把残留放完而不是继续等水位
            self._player.drain()
            self._sink.on_response(False)
            return

        if kind == proto.ERROR:
            detail = event.get("error") or {}
            message = detail.get("message") or json.dumps(detail, ensure_ascii=False)
            code = str(detail.get("code") or "")
            fatal = code in ("invalid_api_key", "unauthorized", "access_denied") or "quota" in message
            logger.error("实时服务返回错误: %s", message)
            self._sink.on_error(message, fatal=fatal)
            return
