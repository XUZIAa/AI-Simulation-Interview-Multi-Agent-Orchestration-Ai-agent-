from __future__ import annotations

import asyncio
import faulthandler
import logging
import sys

import qasync
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from ..app.async_utils import set_default_error_handler
from ..app.context import AppContext
from ..core.logging_setup import setup_logging
from ..core.paths import log_dir
from .main_window import MainWindow
from .theme import FONT_FAMILY, build_stylesheet

logger = logging.getLogger(__name__)
_crash_file = None


def _enable_crash_dump() -> None:
    global _crash_file
    try:
        _crash_file = (log_dir() / "crash.log").open("w", encoding="utf-8")
        faulthandler.enable(_crash_file)
    except Exception:
        logger.warning("无法启用崩溃转储", exc_info=True)


def _configure(app: QApplication) -> None:
    # 强制内置 Fusion 样式：不依赖原生样式插件，打包后跨机稳定，外观由样式表统一接管
    app.setStyle("Fusion")
    app.setApplicationName("AI 模拟面试")
    app.setOrganizationName("Interviewer.AI")
    app.setStyleSheet(build_stylesheet())
    app.setFont(QFont(FONT_FAMILY.split(",")[0].strip('"'), 10))


async def _lifecycle(context: AppContext, window: MainWindow, closed: asyncio.Event) -> None:
    """启动失败在此清理；正常退出的清理交给窗口关闭流程。

    退出清理不能放在这里的 finally：那时 aboutToQuit 已经触发、
    事件循环正在收尾，httpx 关连接池会抛 anyio.NoEventLoopError。
    """
    try:
        await context.initialize()
        await window.post_init()
    except BaseException:
        logger.exception("应用启动失败")
        await context.shutdown()
        raise
    logger.info("界面初始化完成，进入主循环")
    await closed.wait()


def run() -> int:
    setup_logging()
    _enable_crash_dump()
    logger.info("应用启动 frozen=%s", getattr(sys, "frozen", False))
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)
    _configure(app)

    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)

    closed = asyncio.Event()
    app.aboutToQuit.connect(closed.set)

    context = AppContext()
    window = MainWindow(context)
    set_default_error_handler(window.toast_error)

    # 关键：在事件循环启动前、于主线程浅栈处显示窗口。
    # 若放到 qasync 的异步回调里再 show()，打包版会因调用栈过深叠加 Qt 原生深调用而栈溢出崩溃。
    window.present()
    logger.info("主窗口已显示 visible=%s maximized=%s", window.isVisible(), window.isMaximized())

    try:
        with loop:
            loop.run_until_complete(_lifecycle(context, window, closed))
    except Exception:
        logger.exception("事件循环异常退出")
        return 1
    logger.info("应用退出")
    return 0
