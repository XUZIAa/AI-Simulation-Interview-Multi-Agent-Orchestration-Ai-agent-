from __future__ import annotations

import asyncio
import contextlib
import logging

from ..core.config import ConfigStore, config_store
from .base import ChatClient, user

logger = logging.getLogger(__name__)

ROLE_DIRECTOR = "director"
ROLE_ANALYST = "analyst"
ROLE_GUARD = "guard"
ROLE_ASSIST = "assist"
ALL_ROLES: tuple[str, ...] = (ROLE_DIRECTOR, ROLE_ANALYST, ROLE_GUARD, ROLE_ASSIST)

_ROLE_TIMEOUTS: dict[str, float] = {
    ROLE_DIRECTOR: 20.0,
    ROLE_ANALYST: 240.0,
    ROLE_GUARD: 8.0,
    ROLE_ASSIST: 15.0,
}


class LLMRouter:
    """按角色分发模型客户端。同一 (provider, model) 复用连接池。"""

    def __init__(self, store: ConfigStore | None = None) -> None:
        self._store = store or config_store()
        self._clients: dict[tuple[str, str, float], ChatClient] = {}

    def client(self, role: str) -> ChatClient:
        settings = self._store.settings
        catalog = settings.chat_catalog(role)
        model = settings.chat_model(role)
        timeout = _ROLE_TIMEOUTS.get(role, 60.0)
        key = (catalog.key, model, timeout)
        cached = self._clients.get(key)
        if cached is not None:
            return cached
        api_key = self._store.require_api_key(catalog.key)
        client = ChatClient(
            provider_key=catalog.key,
            base_url=catalog.base_url,
            api_key=api_key,
            model=model,
            timeout=timeout,
        )
        self._clients[key] = client
        logger.info("创建模型客户端 role=%s provider=%s model=%s", role, catalog.key, model)
        return client

    async def warm(self, *roles: str) -> None:
        """预建客户端与 TLS 连接。

        首次调用要加载模块、握手、建连接池，这些是同步 CPU 开销。压在语音链路
        启动之后会抢占事件循环，音频上行与播放推送都会被拖慢，听感就是开场
        几秒一卡一卡。放在还没有音频的准备阶段做，等的是同一份时间但无感。
        """

        async def ping(role: str) -> None:
            with contextlib.suppress(Exception):
                await self.client(role).complete([user("hi")], max_tokens=1, temperature=0.0)

        await asyncio.gather(*(ping(role) for role in roles))

    async def invalidate(self) -> None:
        clients = list(self._clients.values())
        self._clients.clear()
        for client in clients:
            await client.aclose()

    async def aclose(self) -> None:
        await self.invalidate()

    def missing_credentials(self) -> list[str]:
        """返回缺少 API Key 的供应商，UI 用它做启动前检查。"""
        settings = self._store.settings
        missing: list[str] = []
        for role in ALL_ROLES:
            catalog = settings.chat_catalog(role)
            if not self._store.get_api_key(catalog.key) and catalog.key not in missing:
                missing.append(catalog.key)
        realtime = settings.realtime.catalog()
        if not self._store.get_api_key(realtime.credential_key) and realtime.credential_key not in missing:
            missing.append(realtime.credential_key)
        return missing
