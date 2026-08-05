from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from typing import Any, TypeVar

from ..core.errors import InterviewerError

logger = logging.getLogger(__name__)

T = TypeVar("T")

ErrorHandler = Callable[[str, str], None]
_default_error_handler: ErrorHandler | None = None


def set_default_error_handler(handler: ErrorHandler) -> None:
    """UI 层注册一个全局错误提示回调，异步任务失败时统一弹出。"""
    global _default_error_handler
    _default_error_handler = handler


def _report(message: str, detail: str) -> None:
    if _default_error_handler is not None:
        _default_error_handler(message, detail)
    else:
        logger.error("%s | %s", message, detail)


_alive: set[asyncio.Task[Any]] = set()


def spawn(
    coro: Coroutine[Any, Any, T],
    *,
    on_success: Callable[[T], None] | None = None,
    on_error: Callable[[Exception], None] | None = None,
    context: str = "操作",
) -> asyncio.Task[T]:
    """把一个协程调度到当前事件循环，并统一处理成功与失败。

    调用方通常不保留返回值，所以这里自己持强引用，避免任务被 GC 中断。
    """
    task: asyncio.Task[T] = asyncio.ensure_future(coro)
    _alive.add(task)
    task.add_done_callback(_alive.discard)

    def done(finished: asyncio.Task[T]) -> None:
        if finished.cancelled():
            return
        error = finished.exception()
        if error is not None:
            _handle_error(error, on_error, context)
            return
        if on_success is not None:
            try:
                on_success(finished.result())
            except Exception:
                logger.exception("成功回调执行失败")

    task.add_done_callback(done)
    return task


def _handle_error(
    error: BaseException, on_error: Callable[[Exception], None] | None, context: str
) -> None:
    if not isinstance(error, Exception):
        raise error
    logger.exception("%s失败", context, exc_info=error)
    if on_error is not None:
        on_error(error)
        return
    if isinstance(error, InterviewerError):
        _report(error.user_message, error.detail)
    else:
        _report(f"{context}失败", str(error))
