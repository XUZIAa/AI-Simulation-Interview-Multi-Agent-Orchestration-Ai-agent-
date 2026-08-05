from __future__ import annotations

from enum import Enum
from typing import Protocol

from ..domain.interview import InterviewState
from ..domain.persona import PersonaContract


class Page(str, Enum):
    DASHBOARD = "dashboard"
    PREPARE = "prepare"
    PERSONA = "persona"
    MISTAKES = "mistakes"
    GROWTH = "growth"
    SETTINGS = "settings"

    @property
    def title(self) -> str:
        return _TITLES[self]

    @property
    def glyph(self) -> str:
        return _GLYPHS[self]


_TITLES: dict[Page, str] = {
    Page.DASHBOARD: "工作台",
    Page.PREPARE: "准备面试",
    Page.PERSONA: "人设工坊",
    Page.MISTAKES: "错题本",
    Page.GROWTH: "成长轨迹",
    Page.SETTINGS: "设置",
}

_GLYPHS: dict[Page, str] = {
    Page.DASHBOARD: "dashboard",
    Page.PREPARE: "prepare",
    Page.PERSONA: "persona",
    Page.MISTAKES: "mistakes",
    Page.GROWTH: "growth",
    Page.SETTINGS: "settings",
}

# 顶部主导航。设置不在其中，单独放到右侧操作区
TOP_NAV: tuple[Page, ...] = (
    Page.DASHBOARD,
    Page.PREPARE,
    Page.PERSONA,
    Page.MISTAKES,
    Page.GROWTH,
)


class Navigator(Protocol):
    """视图通过它切换页面、进出面试、弹提示，不直接依赖主窗口。"""

    def navigate(self, page: Page) -> None: ...

    def open_prepare(self, *, persona: PersonaContract | None = None) -> None: ...

    def start_interview(self, state: InterviewState) -> None: ...

    def open_review(self, session_id: int, *, generate: bool = False) -> None: ...

    def toast(self, message: str, *, kind: str = "info") -> None: ...
