from __future__ import annotations

import logging

from ..core.config import ConfigStore, config_store
from ..core.events import EventBus
from ..data.database import Database, database
from ..data.repositories import (
    LibraryRepository,
    PersonaRepository,
    ReviewRepository,
    SessionRepository,
)
from ..llm.router import LLMRouter
from ..orchestration.engine import InterviewEngine
from ..orchestration.prepare_service import PrepareService
from ..orchestration.recovery import RecoveryService
from ..orchestration.review_service import ReviewService

logger = logging.getLogger(__name__)


class AppContext:
    """应用级依赖容器。整个进程共享同一份，UI 通过它访问所有能力。"""

    def __init__(self) -> None:
        self.config: ConfigStore = config_store()
        self.bus = EventBus()
        self.database: Database = database()
        self.router = LLMRouter(self.config)

        self.personas = PersonaRepository(self.database)
        self.library = LibraryRepository()
        self.sessions = SessionRepository(self.database)
        self.reviews = ReviewRepository(self.database)

        self.engine = InterviewEngine(
            bus=self.bus,
            router=self.router,
            store=self.config,
            sessions=self.sessions,
        )
        self.prepare = PrepareService(
            router=self.router,
            library=self.library,
            sessions=self.sessions,
            personas=self.personas,
        )
        self.review = ReviewService(
            bus=self.bus,
            router=self.router,
            sessions=self.sessions,
            reviews=self.reviews,
        )
        self.recovery = RecoveryService(self.sessions)

    async def initialize(self) -> None:
        await self.database.start()
        await self.personas.ensure_builtins()
        logger.info("应用上下文初始化完成")

    async def shutdown(self) -> None:
        if self.engine.running:
            await self.engine.stop(aborted=True)
        await self.router.aclose()
        await self.database.stop()
        logger.info("应用上下文已关闭")

    async def reload_models(self) -> None:
        """设置变更后清空模型客户端缓存，下次调用按新配置重建。"""
        await self.router.invalidate()
