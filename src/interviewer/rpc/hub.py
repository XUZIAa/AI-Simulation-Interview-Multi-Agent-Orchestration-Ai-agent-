from __future__ import annotations

import asyncio
import contextlib
import logging
import re
from dataclasses import fields, is_dataclass
from typing import Any

from fastapi import WebSocket

from ..core import events as ev
from ..core.events import EventBus
from .serialize import to_json

logger = logging.getLogger(__name__)

# 事件总线里的全部事件，逐一广播。少一个前端就瞎一块，所以这里按类反射而非手写清单。
_EVENT_TYPES: tuple[type[ev.Event], ...] = tuple(
    obj
    for obj in vars(ev).values()
    if isinstance(obj, type) and is_dataclass(obj) and issubclass(obj, ev.Event) and obj is not ev.Event
)

# 高频事件：每 100ms 一发，堆积起来会把 WS 打满，只保留最新一份
_COALESCED = {"audio_level", "elapsed_tick"}
_FLUSH_INTERVAL = 0.05
_QUEUE_LIMIT = 256


def event_name(cls: type) -> str:
    """AudioLevel -> audio_level。前端按这个名字分派。"""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", cls.__name__).lower()


EVENT_NAMES: tuple[str, ...] = tuple(event_name(t) for t in _EVENT_TYPES)


class EventHub:
    """把后端事件总线桥到 WebSocket。

    事件在引擎的事件循环里同步发出，而 WS 发送是异步的，中间必须有队列；
    否则一次网络抖动就会把编排循环拖住。
    """

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._clients: set[WebSocket] = set()
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=_QUEUE_LIMIT)
        self._latest: dict[str, dict[str, Any]] = {}
        self._unsubs: list[Any] = []
        self._pump: asyncio.Task[None] | None = None
        self._dropped = 0

    # ---------- 生命周期 ----------

    def start(self) -> None:
        if self._unsubs:
            return
        for cls in _EVENT_TYPES:
            self._unsubs.append(self._bus.subscribe(cls, self._make_handler(cls)))
        self._pump = asyncio.create_task(self._flush_loop(), name="rpc-event-pump")
        logger.info("事件桥已启动，转发 %d 类事件", len(_EVENT_TYPES))

    async def stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs = []
        if self._pump is not None:
            self._pump.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._pump
            self._pump = None
        for ws in list(self._clients):
            with contextlib.suppress(Exception):
                await ws.close()
        self._clients.clear()

    # ---------- 连接管理 ----------

    def attach(self, ws: WebSocket) -> None:
        self._clients.add(ws)

    def detach(self, ws: WebSocket) -> None:
        self._clients.discard(ws)

    @property
    def client_count(self) -> int:
        return len(self._clients)

    # ---------- 推送 ----------

    def _make_handler(self, cls: type[ev.Event]):
        name = event_name(cls)

        def handler(event: ev.Event) -> None:
            payload = {f.name: to_json(getattr(event, f.name)) for f in fields(event)}
            self.publish(name, payload)

        return handler

    def publish(self, name: str, data: dict[str, Any]) -> None:
        """从任意上下文投递一条事件。同步返回，绝不阻塞调用方。"""
        if name in _COALESCED:
            self._latest[name] = data
            return
        frame = {"event": name, "data": data}
        try:
            self._queue.put_nowait(frame)
        except asyncio.QueueFull:
            # 丢最旧的一条，保住新事件：卡住编排比丢一帧动画数据严重得多
            with contextlib.suppress(asyncio.QueueEmpty):
                self._queue.get_nowait()
            self._dropped += 1
            with contextlib.suppress(asyncio.QueueFull):
                self._queue.put_nowait(frame)

    async def _flush_loop(self) -> None:
        while True:
            await asyncio.sleep(_FLUSH_INTERVAL)
            frames: list[dict[str, Any]] = []
            while not self._queue.empty():
                with contextlib.suppress(asyncio.QueueEmpty):
                    frames.append(self._queue.get_nowait())
            for name, data in self._latest.items():
                frames.append({"event": name, "data": data})
            self._latest.clear()
            if not frames or not self._clients:
                continue
            await self._send(frames)

    async def _send(self, frames: list[dict[str, Any]]) -> None:
        dead: list[WebSocket] = []
        for ws in list(self._clients):
            try:
                for frame in frames:
                    await ws.send_json(frame)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._clients.discard(ws)
        if dead:
            logger.info("移除 %d 个已断开的事件订阅端", len(dead))

    @property
    def dropped(self) -> int:
        return self._dropped
