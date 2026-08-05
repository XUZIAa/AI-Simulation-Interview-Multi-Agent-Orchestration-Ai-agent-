from __future__ import annotations

import logging
from typing import ClassVar

from ..llm.base import ChatClient
from ..llm.router import LLMRouter

logger = logging.getLogger(__name__)


class Agent:
    """所有 Agent 的共同外壳。角色决定它用哪个模型。"""

    role: ClassVar[str]

    def __init__(self, router: LLMRouter) -> None:
        self._router = router

    @property
    def client(self) -> ChatClient:
        return self._router.client(self.role)


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def trim(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"
