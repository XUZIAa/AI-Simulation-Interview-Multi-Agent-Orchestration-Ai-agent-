from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from ..core.paths import database_file
from .models import Base

logger = logging.getLogger(__name__)

_PRAGMAS: tuple[tuple[str, Any], ...] = (
    ("journal_mode", "WAL"),
    ("synchronous", "NORMAL"),
    ("foreign_keys", "ON"),
    ("busy_timeout", 8000),
    ("cache_size", -32000),
    ("temp_store", "MEMORY"),
)


class Database:
    """单例式数据库门面。SQLite 单写者，写操作一律走同一个 engine。"""

    def __init__(self) -> None:
        self._engine: AsyncEngine | None = None
        self._factory: async_sessionmaker[AsyncSession] | None = None

    @property
    def engine(self) -> AsyncEngine:
        if self._engine is None:
            raise RuntimeError("数据库尚未初始化")
        return self._engine

    async def start(self) -> None:
        if self._engine is not None:
            return
        url = f"sqlite+aiosqlite:///{database_file().as_posix()}"
        engine = create_async_engine(url, echo=False, future=True, pool_pre_ping=True)

        @event.listens_for(engine.sync_engine, "connect")
        def _apply_pragmas(dbapi_conn: Any, _record: Any) -> None:
            cursor = dbapi_conn.cursor()
            try:
                for name, value in _PRAGMAS:
                    cursor.execute(f"PRAGMA {name}={value}")
            finally:
                cursor.close()

        self._engine = engine
        self._factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("数据库就绪: %s", database_file())

    async def stop(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None
            self._factory = None

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """只读或短事务使用。"""
        if self._factory is None:
            raise RuntimeError("数据库尚未初始化")
        async with self._factory() as session:
            yield session

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncSession]:
        """写操作使用，出错自动回滚。"""
        if self._factory is None:
            raise RuntimeError("数据库尚未初始化")
        async with self._factory() as session, session.begin():
            yield session


_db: Database | None = None


def database() -> Database:
    global _db
    if _db is None:
        _db = Database()
    return _db
