from __future__ import annotations

import inspect
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

from .types import AnnotationKind, DriftKind, InterviewPhase, ScoreDimension, StarElement, TurnIntent

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class Event:
    """所有事件的基类，仅作类型锚点。"""


@dataclass(slots=True)
class RealtimeStateChanged(Event):
    connected: bool
    reason: str = ""


@dataclass(slots=True)
class SpeechActivity(Event):
    """VAD 判定的说话起止，用于 UI 高亮当前发言人。"""

    speaking: bool


@dataclass(slots=True)
class AudioLevel(Event):
    """0.0~1.0 的瞬时能量，驱动波形动画。"""

    candidate: float
    interviewer: float


@dataclass(slots=True)
class TranscriptDelta(Event):
    speaker: str
    text: str


@dataclass(slots=True)
class TranscriptCommitted(Event):
    turn_id: int
    speaker: str
    text: str
    started_at_ms: int
    duration_ms: int


@dataclass(slots=True)
class PhaseChanged(Event):
    phase: InterviewPhase
    reason: str


@dataclass(slots=True)
class DirectorDecided(Event):
    intent: TurnIntent
    brief: str
    target_skill: str
    follow_up_depth: int


@dataclass(slots=True)
class DriftDetected(Event):
    kind: DriftKind
    excerpt: str
    repaired: bool


@dataclass(slots=True)
class ReanchorPerformed(Event):
    turn_index: int
    trigger: str


@dataclass(slots=True)
class CopilotHint(Event):
    keywords: list[str]
    outline: list[str]
    caution: str = ""


@dataclass(slots=True)
class StarProgress(Event):
    present: set[StarElement]
    missing: set[StarElement]
    is_behavioral: bool


@dataclass(slots=True)
class InterruptionFired(Event):
    by_interviewer: bool
    reason: str


@dataclass(slots=True)
class LiveAnnotation(Event):
    turn_id: int
    kind: AnnotationKind
    comment: str


@dataclass(slots=True)
class LiveScoreUpdated(Event):
    scores: dict[ScoreDimension, float]


@dataclass(slots=True)
class CodeSubmitted(Event):
    language: str
    source: str


@dataclass(slots=True)
class EngineFailure(Event):
    user_message: str
    detail: str = ""
    fatal: bool = False


@dataclass(slots=True)
class ProsodySnapshot(Event):
    words_per_minute: float
    filler_ratio: float
    pause_ratio: float
    longest_pause_ms: int


@dataclass(slots=True)
class ReviewProgress(Event):
    stage: str
    percent: int
    detail: str = ""


@dataclass(slots=True)
class ElapsedTick(Event):
    elapsed_ms: int
    remaining_ms: int


E = TypeVar("E", bound=Event)
Handler = Callable[[Any], None | Awaitable[None]]


@dataclass(slots=True, eq=False)
class _Subscription:
    """eq=False：按身份比较，同一个 handler 订阅两次时取消才不会摘错。"""

    handler: Handler
    is_async: bool = field(default=False)


class EventBus:
    """进程内同步事件总线。异步处理器会被投递到当前事件循环。"""

    def __init__(self) -> None:
        self._subs: dict[type[Event], list[_Subscription]] = defaultdict(list)
        # 必须持强引用，否则 fire-and-forget 的任务可能被 GC 中断
        self._tasks: set[Any] = set()

    def subscribe(self, event_type: type[E], handler: Callable[[E], Any]) -> Callable[[], None]:
        sub = _Subscription(handler, inspect.iscoroutinefunction(handler))
        self._subs[event_type].append(sub)

        def unsubscribe() -> None:
            with_type = self._subs.get(event_type)
            if with_type and sub in with_type:
                with_type.remove(sub)

        return unsubscribe

    def emit(self, event: Event) -> None:
        for sub in list(self._subs.get(type(event), ())):
            try:
                result = sub.handler(event)
                if sub.is_async and result is not None:
                    self._spawn(result)
            except Exception:
                logger.exception("事件处理器异常: %s", type(event).__name__)

    def _spawn(self, coro: Any) -> None:
        import asyncio

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.warning("无运行中的事件循环，异步事件处理器被丢弃")
            return
        task = loop.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        task.add_done_callback(_report_task_failure)

    def clear(self) -> None:
        self._subs.clear()
        self._tasks.clear()


def _report_task_failure(task: Any) -> None:
    if task.cancelled():
        return
    error = task.exception()
    if error is not None:
        logger.error("异步事件处理器失败", exc_info=error)
