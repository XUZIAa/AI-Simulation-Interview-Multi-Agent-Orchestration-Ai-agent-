from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from typing import TypeVar

from ..database import Database, database

T = TypeVar("T")

CHUNK_SIZE = 80


def chunked(items: Sequence[T], size: int = CHUNK_SIZE) -> Iterator[Sequence[T]]:
    """分批切片。SQLite 单写者，批量写入必须切开提交。"""
    for start in range(0, len(items), size):
        yield items[start : start + size]


class Repository:
    def __init__(self, db: Database | None = None) -> None:
        self._db = db or database()

    @property
    def db(self) -> Database:
        return self._db


def dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = value.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(value.strip())
    return result
