from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import secrets
import socket
import sys
from typing import Any

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from starlette.types import ASGIApp

from ..app.context import AppContext
from ..core.errors import InterviewerError
from .api import interviewer_error_handler, router
from .hub import EventHub

logger = logging.getLogger(__name__)

_LOOPBACK = "127.0.0.1"
_HANDSHAKE_PREFIX = "INTERVIEWER_RPC "
_OPEN_PATHS = frozenset({"/openapi.json", "/docs", "/redoc", "/docs/oauth2-redirect"})

# 桌面前端跑在 WebView 里，向本机端口发请求属于跨域，必须显式放行来源。
# 开发态是 Vite 的地址，打包态由 Tauri 提供。真正的门禁是 token，这里只是
# 让浏览器的同源策略不要提前掐断请求。
_ALLOWED_ORIGINS = (
    "http://localhost:1420",
    "http://127.0.0.1:1420",
    "http://tauri.localhost",
    "https://tauri.localhost",
    "tauri://localhost",
)


class TokenGuard(BaseHTTPMiddleware):
    """本机回环也不等于可信：同机任何进程都能连上来。

    面试引擎能花钱调模型、能读写简历、能取用密钥，因此每个请求都必须带
    启动时生成的一次性 token。
    """

    def __init__(self, app: ASGIApp, token: str) -> None:
        super().__init__(app)
        self._token = token

    async def dispatch(self, request: Any, call_next: Any) -> Any:
        # 预检请求不带自定义头，拦下它等于让所有跨域调用直接失败
        if request.method == "OPTIONS" or request.url.path in _OPEN_PATHS:
            return await call_next(request)
        supplied = request.headers.get("x-interviewer-token") or request.query_params.get("token")
        if not supplied or not secrets.compare_digest(supplied, self._token):
            return JSONResponse(status_code=401, content={"detail": "token 不正确"})
        return await call_next(request)


def create_app(ctx: AppContext, token: str) -> FastAPI:
    app = FastAPI(
        title="AI 模拟面试 本机接口",
        version="1",
        description="桌面前端与 Python 后端之间的本机通道。仅监听回环地址，需 token 认证。",
    )
    app.state.ctx = ctx
    app.state.hub = EventHub(ctx.bus)
    app.state.token = token
    app.add_middleware(TokenGuard, token=token)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(_ALLOWED_ORIGINS),
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["X-Interviewer-Token", "Content-Type"],
        max_age=600,
    )
    app.add_exception_handler(InterviewerError, interviewer_error_handler)
    app.include_router(router)

    @app.websocket("/events")
    async def events(ws: WebSocket) -> None:
        supplied = ws.query_params.get("token") or ws.headers.get("x-interviewer-token")
        if not supplied or not secrets.compare_digest(supplied, token):
            await ws.close(code=4401)
            return
        await ws.accept()
        hub: EventHub = app.state.hub
        hub.attach(ws)
        logger.info("事件订阅端已连接，当前 %d 个", hub.client_count)
        try:
            while True:
                # 前端不通过这条通道发指令，收到什么都忽略，只用它感知断连
                await ws.receive_text()
        except WebSocketDisconnect:
            pass
        except Exception:
            logger.debug("事件通道异常", exc_info=True)
        finally:
            hub.detach(ws)

    return app


def reserve_port(preferred: int = 0) -> tuple[socket.socket, int]:
    """先占住端口再交给 uvicorn，避免「报告端口」与「真正监听」之间被别人抢走。"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((_LOOPBACK, preferred))
    sock.listen(128)
    return sock, sock.getsockname()[1]


def announce(port: int, token: str) -> None:
    """把连接信息写到 stdout 供父进程读取。

    固定端口会撞车，所以端口由系统分配；父进程只能从这里得知结果。
    """
    payload = json.dumps({"port": port, "token": token, "host": _LOOPBACK}, ensure_ascii=False)
    sys.stdout.write(f"{_HANDSHAKE_PREFIX}{payload}\n")
    sys.stdout.flush()


class RpcServer:
    """可嵌入现有事件循环的服务封装。

    Qt 版本仍在跑同一个 loop，所以这里不能自己 run()，只能挂任务。
    """

    def __init__(self, ctx: AppContext, *, port: int = 0, token: str = "") -> None:
        self._ctx = ctx
        self._token = token or secrets.token_urlsafe(32)
        self._sock, self._port = reserve_port(port)
        self._app = create_app(ctx, self._token)
        self._server: uvicorn.Server | None = None
        self._task: asyncio.Task[None] | None = None

    @property
    def port(self) -> int:
        return self._port

    @property
    def token(self) -> str:
        return self._token

    @property
    def hub(self) -> EventHub:
        return self._app.state.hub

    async def start(self) -> None:
        config = uvicorn.Config(
            self._app,
            host=_LOOPBACK,
            log_config=None,
            access_log=False,
            lifespan="on",
            ws_ping_interval=20,
            ws_ping_timeout=20,
        )
        self._server = uvicorn.Server(config)
        self.hub.start()
        self._task = asyncio.create_task(
            self._server.serve(sockets=[self._sock]), name="rpc-server"
        )
        # 等它真正进入监听，之后前端一连就能通
        for _ in range(200):
            if self._server.started:
                break
            await asyncio.sleep(0.02)
        logger.info("本机接口已就绪 http://%s:%d", _LOOPBACK, self._port)

    async def stop(self) -> None:
        await self.hub.stop()
        if self._server is not None:
            self._server.should_exit = True
        if self._task is not None:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await asyncio.wait_for(self._task, timeout=5)
            self._task = None
        with contextlib.suppress(Exception):
            self._sock.close()
        logger.info("本机接口已关闭")
