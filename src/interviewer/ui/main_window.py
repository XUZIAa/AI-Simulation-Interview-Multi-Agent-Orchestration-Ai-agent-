from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6.QtCore import (
    QPropertyAnimation,
    Qt,
    QTimer,
)
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..app.async_utils import spawn
from ..app.context import AppContext
from ..domain.interview import InterviewState
from ..domain.persona import PersonaContract
from . import icons
from .chrome import AppWindow
from .navigation import TOP_NAV, Page
from .theme import Color
from .views.dashboard import DashboardView
from .views.growth import GrowthView
from .views.interview_room import InterviewRoomView
from .views.mistakes import MistakesView
from .views.persona_workshop import PersonaWorkshopView
from .views.prepare import PrepareView
from .views.review import ReviewView
from .views.settings import SettingsView

logger = logging.getLogger(__name__)


class NavItem(QWidget):
    """顶部导航项。线性图标 + 标题，选中态用胶囊底，图标同步换色。"""

    def __init__(
        self,
        page: Page,
        on_click: Callable[[Page], None],
        *,
        icon_only: bool = False,
    ) -> None:
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.page = page
        self._checked = False
        self._hover = False
        self._on_click = on_click
        self._icon_only = icon_only
        self.setFixedHeight(36)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        row = QHBoxLayout(self)
        pad = 9 if icon_only else 12
        row.setContentsMargins(pad, 0, pad, 0)
        row.setSpacing(8)

        self._glyph = QLabel()
        self._glyph.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(self._glyph)

        self._text: QLabel | None = None
        if not icon_only:
            self._text = QLabel(page.title)
            row.addWidget(self._text)
        else:
            self.setToolTip(page.title)
        self._render()

    def setChecked(self, value: bool) -> None:
        if value != self._checked:
            self._checked = value
            self._render()

    def isChecked(self) -> bool:
        return self._checked

    def _render(self) -> None:
        if self._checked:
            tone, weight, bg = Color.PRIMARY_TEXT, 650, Color.PRIMARY_SOFT
        elif self._hover:
            tone, weight, bg = Color.TEXT, 600, Color.SURFACE_HOVER
        else:
            tone, weight, bg = Color.TEXT_MUTED, 600, "transparent"
        self.setStyleSheet(
            f"NavItem {{ background: {bg}; border-radius: 9px; }}"
            f"QLabel {{ color: {tone}; font-size: 14px; font-weight: {weight}; background: transparent; }}"
        )
        self._glyph.setPixmap(icons.pixmap(self.page.glyph, size=18, color=tone))

    def enterEvent(self, event) -> None:
        self._hover = True
        self._render()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover = False
        self._render()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        self._on_click(self.page)
        super().mousePressEvent(event)


class Toast(QFrame):
    """顶部居中的轻量通知，几秒后淡出。"""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("Toast")
        self._label = QLabel("")
        self._label.setWordWrap(True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 12, 18, 12)
        layout.addWidget(self._label)
        self._effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._effect)
        self._anim = QPropertyAnimation(self._effect, b"opacity", self)
        self._anim.setDuration(220)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._fade_out)
        self.hide()

    def show_message(self, text: str, kind: str) -> None:
        accent = {
            "info": Color.PRIMARY,
            "success": Color.SUCCESS,
            "warning": Color.WARNING,
            "error": Color.DANGER,
        }.get(kind, Color.PRIMARY)
        self._label.setText(text)
        self.setStyleSheet(
            f"#Toast {{ background: {Color.SURFACE}; border: 1px solid {Color.BORDER_STRONG}; "
            f"border-left: 4px solid {accent}; border-radius: 12px; }}"
            f"QLabel {{ color: {Color.TEXT}; font-size: 13px; font-weight: 500; }}"
        )
        self.adjustSize()
        self.setFixedWidth(min(460, max(280, self._label.sizeHint().width() + 60)))
        self._reposition()
        self.show()
        self.raise_()
        self._anim.stop()
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.start()
        self._timer.start(3600)

    def _fade_out(self) -> None:
        self._anim.stop()
        self._anim.setStartValue(1.0)
        self._anim.setEndValue(0.0)
        self._anim.start()
        QTimer.singleShot(240, self.hide)

    def _reposition(self) -> None:
        parent = self.parentWidget()
        if parent is not None:
            self.move((parent.width() - self.width()) // 2, 24)


class MainWindow(AppWindow):
    def __init__(self, context: AppContext) -> None:
        super().__init__(title="AI 模拟面试")
        self._ctx = context
        self.setMinimumSize(880, 620)

        self._nav_buttons: dict[Page, NavItem] = {}
        self._build_ui()
        self._toast = Toast(self.content_host())

    def _build_ui(self) -> None:
        host = self.content_host()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._topbar = self._build_topbar()
        layout.addWidget(self._topbar)

        self._stack = QStackedWidget()
        # 必须用作用域选择器：裸 background 声明会继承到所有后代，
        # 覆盖掉 app 级样式表里的 #Card / #Primary 背景。
        self._stack.setObjectName("ViewStack")
        layout.addWidget(self._stack, 1)

        # 懒加载：视图在首次进入时才构建。启动只挂空壳，既加快启动，
        # 也避免重量级控件（如面试间的摄像头）在主窗口首次绘制时被牵连初始化。
        self._factories = {
            Page.DASHBOARD: DashboardView,
            Page.PREPARE: PrepareView,
            Page.PERSONA: PersonaWorkshopView,
            Page.MISTAKES: MistakesView,
            Page.GROWTH: GrowthView,
            Page.SETTINGS: SettingsView,
        }
        self._views: dict[Page, QWidget] = {}
        self._interview_room: InterviewRoomView | None = None
        self._review_view: ReviewView | None = None

    def _ensure_view(self, page: Page) -> QWidget:
        view = self._views.get(page)
        if view is None:
            view = self._factories[page](self._ctx, self)
            self._views[page] = view
            self._stack.addWidget(view)
        return view

    def _ensure_room(self) -> InterviewRoomView:
        if self._interview_room is None:
            self._interview_room = InterviewRoomView(self._ctx, self)
            self._stack.addWidget(self._interview_room)
        return self._interview_room

    def _ensure_review(self) -> ReviewView:
        if self._review_view is None:
            self._review_view = ReviewView(self._ctx, self)
            self._stack.addWidget(self._review_view)
        return self._review_view

    def _build_topbar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("TopBar")
        bar.setFixedHeight(58)
        row = QHBoxLayout(bar)
        row.setContentsMargins(20, 0, 20, 0)
        row.setSpacing(6)

        row.addWidget(self._build_brand())
        row.addSpacing(26)

        for page in TOP_NAV:
            item = NavItem(page, self.navigate)
            self._nav_buttons[page] = item
            row.addWidget(item)

        row.addStretch(1)
        row.addWidget(self._build_privacy_note())
        row.addSpacing(12)

        settings = NavItem(Page.SETTINGS, self.navigate, icon_only=True)
        self._nav_buttons[Page.SETTINGS] = settings
        row.addWidget(settings)
        return bar

    def _build_brand(self) -> QWidget:
        host = QWidget()
        row = QHBoxLayout(host)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)

        mark = QLabel()
        mark.setFixedSize(30, 30)
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setPixmap(icons.pixmap("target", size=18, color=Color.TEXT_ON_PRIMARY, width=2.1))
        mark.setStyleSheet(f"background: {Color.PRIMARY}; border-radius: 9px;")
        row.addWidget(mark)

        name = QLabel("AI 模拟面试")
        name.setStyleSheet(f"color: {Color.TEXT}; font-size: 15px; font-weight: 700;")
        row.addWidget(name)
        return host

    def _build_privacy_note(self) -> QWidget:
        host = QWidget()
        row = QHBoxLayout(host)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        mark = QLabel()
        mark.setPixmap(icons.pixmap("shield", size=14, color=Color.SUCCESS))
        row.addWidget(mark)
        text = QLabel("本地运行 · 数据不出本机")
        text.setStyleSheet(f"color: {Color.TEXT_FAINT}; font-size: 11px;")
        row.addWidget(text)
        return host

    # ------------------------------------------------------------------
    # Navigator
    # ------------------------------------------------------------------

    def navigate(self, page: Page) -> None:
        self._topbar.setVisible(True)
        view = self._ensure_view(page)
        self._stack.setCurrentWidget(view)
        for key, btn in self._nav_buttons.items():
            btn.setChecked(key is page)
        on_show = getattr(view, "on_show", None)
        if callable(on_show):
            on_show()

    def open_prepare(self, *, persona: PersonaContract | None = None) -> None:
        self.navigate(Page.PREPARE)
        if persona is not None:
            view = self._views.get(Page.PREPARE)
            if isinstance(view, PrepareView):
                view.preselect_persona(persona)

    def start_interview(self, state: InterviewState) -> None:
        self._topbar.setVisible(False)
        room = self._ensure_room()
        self._stack.setCurrentWidget(room)
        room.begin(state)

    def open_review(self, session_id: int, *, generate: bool = False) -> None:
        self._topbar.setVisible(True)
        for btn in self._nav_buttons.values():
            btn.setChecked(False)
        review = self._ensure_review()
        self._stack.setCurrentWidget(review)
        review.show_review(session_id, generate=generate)

    def toast(self, message: str, *, kind: str = "info") -> None:
        self._toast.show_message(message, kind)

    def toast_error(self, message: str, detail: str) -> None:
        logger.error("UI 错误提示: %s | %s", message, detail)
        self._toast.show_message(message, "error")

    async def post_init(self) -> None:
        self.navigate(Page.DASHBOARD)
        interrupted = await self._ctx.recovery.scan()
        if interrupted:
            self.toast(f"检测到 {len(interrupted)} 场未完成的面试，可在工作台查看", kind="warning")
        dashboard = self._views.get(Page.DASHBOARD)
        on_show = getattr(dashboard, "on_show", None) if dashboard is not None else None
        if callable(on_show):
            on_show()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "_toast"):
            self._toast._reposition()

    def closeEvent(self, event) -> None:
        if self._ctx.engine.running:
            spawn(self._ctx.engine.stop(aborted=True), context="结束面试")
        super().closeEvent(event)
