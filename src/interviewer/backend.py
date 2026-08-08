"""后端独立进程入口。

Tauri 以 sidecar 方式拉起它：不加载任何 Qt，只跑编排引擎、音频链路与本机接口。
连接信息通过 stdout 握手行回报，父进程据此连上来。
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import signal
import sys

from .app.context import AppContext
from .core.logging_setup import setup_logging
from .rpc.server import RpcServer, announce

logger = logging.getLogger(__name__)


def _parse() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="interviewer-backend")
    parser.add_argument("--port", type=int, default=0, help="0 表示由系统分配")
    parser.add_argument("--token", default="", help="留空则自动生成并在握手行回报")
    return parser.parse_args()


async def _serve(port: int, token: str) -> int:
    ctx = AppContext()
    server = RpcServer(ctx, port=port, token=token)
    stopping = asyncio.Event()

    def request_stop(*_: object) -> None:
        stopping.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError, ValueError):
            loop.add_signal_handler(sig, request_stop)

    try:
        await ctx.initialize()
        await server.start()
    except BaseException:
        logger.exception("后端启动失败")
        await server.stop()
        await ctx.shutdown()
        return 1

    announce(server.port, server.token)
    logger.info("后端进程就绪 port=%d", server.port)

    # 父进程退出会关掉 stdin，据此感知并跟着收摊，避免留下孤儿进程
    stdin_watch = asyncio.create_task(_watch_stdin(stopping), name="stdin-watch")
    try:
        await stopping.wait()
    finally:
        stdin_watch.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await stdin_watch
        await server.stop()
        await ctx.shutdown()
    logger.info("后端进程退出")
    return 0


async def _watch_stdin(stopping: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    while not stopping.is_set():
        line = await loop.run_in_executor(None, sys.stdin.readline)
        if line == "":
            logger.info("父进程已关闭 stdin，开始收尾")
            stopping.set()
            return
        if line.strip() == "shutdown":
            stopping.set()
            return


def main() -> int:
    args = _parse()
    setup_logging()
    logger.info("后端进程启动 frozen=%s", getattr(sys, "frozen", False))
    try:
        return asyncio.run(_serve(args.port, args.token))
    except KeyboardInterrupt:
        return 0
    except Exception:
        logger.exception("后端进程异常退出")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
