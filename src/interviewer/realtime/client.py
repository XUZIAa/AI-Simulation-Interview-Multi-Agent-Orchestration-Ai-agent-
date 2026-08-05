from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
from collections.abc import Callable
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
        )
        self._player = AudioPlayer(
            sample_rate=provider.output_sample_rate,
            device_name=audio.output_device,
            buffer_ms=audio.playback_buffer_ms,
        )
        self._echo_gate = EchoGate(
            self._player,
            capture_rate=provider.input_sample_rate,
            player_rate=provider.output_sample_rate,
        )

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
        await self._send(proto.response_cancel())
        self._responding = False
        self._response_id = None
        self._authorized = False
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
                if self._echo_gate.is_echo(frame):
                    continue
                self._sink.on_candidate_audio(frame, self._clock())
                await self._send(proto.audio_append(base64.b64encode(frame).decode("ascii")))
        except asyncio.CancelledError:
            raise
        except RealtimeClosedError:
            logger.info("上行循环结束：连接已关闭")
        except Exception as exc:
            logger.exception("上行循环异常")
            self._sink.on_error(f"音频上行中断: {exc}", fatal=True)

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
            self._candidate_start_ms = self._clock()
            self._candidate_buffer = ""
            self._sink.on_candidate_speech(True)
            if self._responding:
                await self._cancel_response()
                self._sink.on_barge_in()
            else:
                self._player.clear()
            return

        if kind == proto.SPEECH_STOPPED:
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
            self._interviewer_start_ms = self._clock()
            self._interviewer_buffer = ""
            self._sink.on_response(True)
            return

        if kind == proto.RESPONSE_AUDIO_DELTA:
            chunk = event.get("delta")
            if chunk and self._responding:
                pcm = base64.b64decode(chunk)
                self._player.push(pcm)
                self._sink.on_interviewer_audio(pcm, self._clock())
            return

        if kind in (proto.RESPONSE_TRANSCRIPT_DELTA, proto.RESPONSE_TEXT_DELTA):
            piece = event.get("delta") or ""
            if piece and self._responding:
                self._interviewer_buffer += piece
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
