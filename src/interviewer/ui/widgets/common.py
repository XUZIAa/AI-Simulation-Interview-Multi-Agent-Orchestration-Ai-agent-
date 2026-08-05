from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .. import icons
from ..theme import RADIUS, RADIUS_LG, Color, qcolor


class Panel(QFrame):
    """可靠绘制样式表背景与描边的容器基类。

    纯 QWidget 子类在深层嵌套时不保证绘制样式表背景，容器一律继承本类。
    """

    def __init__(self, *, object_name: str = "", qss: str = "") -> None:
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        if object_name:
            self.setObjectName(object_name)
        if qss:
            self.setStyleSheet(qss)


class Card(QFrame):
    """内容卡片，所有面板的基础容器。白底 + 1px 描边表达层次，不用投影。

    elevated 控制描边强弱：主卡片用清晰描边，次级容器用更淡的描边。
    """

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        padding: int = 20,
        radius: int = RADIUS_LG,
        elevated: bool = True,
    ) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setObjectName("Card")
        border = Color.BORDER if elevated else Color.BORDER_STRONG
        self.setStyleSheet(
            f"#Card {{ background-color: {Color.SURFACE}; border: 1px solid {border}; "
            f"border-radius: {radius}px; }}"
        )
        self._body = QVBoxLayout(self)
        self._body.setContentsMargins(padding, padding, padding, padding)
        self._body.setSpacing(14)

    def body(self) -> QVBoxLayout:
        return self._body

    def add(self, widget: QWidget) -> None:
        self._body.addWidget(widget)

    def add_layout(self, layout: QHBoxLayout | QVBoxLayout) -> None:
        self._body.addLayout(layout)


def label(text: str, *, object_name: str = "", wrap: bool = False, align: Qt.AlignmentFlag | None = None) -> QLabel:
    lbl = QLabel(text)
    if object_name:
        lbl.setObjectName(object_name)
    lbl.setWordWrap(wrap)
    if align is not None:
        lbl.setAlignment(align)
    return lbl


def page_title(text: str) -> QLabel:
    return label(text, object_name="PageTitle")


def lead(text: str, *, wrap: bool = False) -> QLabel:
    return label(text, object_name="Lead", wrap=wrap)


def h1(text: str) -> QLabel:
    return label(text, object_name="H1")


def h2(text: str) -> QLabel:
    return label(text, object_name="H2")


def h3(text: str) -> QLabel:
    return label(text, object_name="H3")


def muted(text: str, *, wrap: bool = False) -> QLabel:
    return label(text, object_name="Muted", wrap=wrap)


def faint(text: str, *, wrap: bool = False) -> QLabel:
    return label(text, object_name="Faint", wrap=wrap)


class AutoLabel(QLabel):
    """内容为空时自动隐藏。

    预留位标签留空文本仍会占据行高与间距，在卡片里表现为莫名的空洞。
    """

    def __init__(
        self,
        text: str = "",
        *,
        color: str = Color.TEXT_MUTED,
        size: int = 13,
        wrap: bool = True,
    ) -> None:
        super().__init__(text)
        self.setWordWrap(wrap)
        self.setStyleSheet(f"color: {color}; font-size: {size}px;")
        self.setVisible(bool(text))

    def setText(self, text: str) -> None:
        super().setText(text)
        self.setVisible(bool(text))


class Badge(QLabel):
    """状态徽章。用颜色区分严重度、阶段、类别。"""

    def __init__(self, text: str, *, color: str = Color.PRIMARY, subtle: bool = True) -> None:
        super().__init__(text)
        self.apply(text, color=color, subtle=subtle)

    def apply(self, text: str, *, color: str = Color.PRIMARY, subtle: bool = True) -> None:
        self.setText(text)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if subtle:
            bg = qcolor(color, 38)
            style = (
                f"background-color: rgba({bg.red()},{bg.green()},{bg.blue()},{bg.alpha()}); "
                f"color: {color};"
            )
        else:
            style = f"background-color: {color}; color: {Color.TEXT_ON_PRIMARY};"
        self.setStyleSheet(
            f"QLabel {{ {style} border-radius: 9px; padding: 3px 11px; font-size: 12px; "
            f"font-weight: 600; }}"
        )


class Chip(QFrame):
    """可选中的胶囊标签，用于技能、话题的多选。"""

    def __init__(self, text: str, *, selectable: bool = False) -> None:
        super().__init__()
        self._selected = False
        self._selectable = selectable
        self._label = QLabel(text)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 5, 12, 5)
        layout.addWidget(self._label)
        self._render()

    def _render(self) -> None:
        if self._selected:
            self.setStyleSheet(
                f"QFrame {{ background-color: {Color.PRIMARY_SOFT}; "
                f"border: 1px solid {Color.PRIMARY}; border-radius: 13px; }}"
                f"QLabel {{ color: {Color.PRIMARY_TEXT}; font-size: 13px; font-weight: 600; }}"
            )
        else:
            self.setStyleSheet(
                f"QFrame {{ background-color: {Color.SURFACE_SUBTLE}; "
                f"border: 1px solid {Color.BORDER}; border-radius: 13px; }}"
                f"QLabel {{ color: {Color.TEXT_MUTED}; font-size: 13px; }}"
            )

    def mousePressEvent(self, event) -> None:
        if self._selectable:
            self.set_selected(not self._selected)
        super().mousePressEvent(event)

    def set_selected(self, value: bool) -> None:
        self._selected = value
        self._render()

    @property
    def selected(self) -> bool:
        return self._selected

    @property
    def text(self) -> str:
        return self._label.text()


class Divider(QFrame):
    def __init__(self, *, vertical: bool = False) -> None:
        super().__init__()
        if vertical:
            self.setFixedWidth(1)
            self.setFrameShape(QFrame.Shape.VLine)
        else:
            self.setFixedHeight(1)
            self.setFrameShape(QFrame.Shape.HLine)
        self.setStyleSheet(f"background-color: {Color.BORDER}; border: none;")


class IconBadge(QLabel):
    """图标底衬。淡色圆角方块 + 线性图标，给指标与条目一个视觉锚点。"""

    def __init__(self, name: str, *, accent: str = Color.PRIMARY, size: int = 36, glyph: int = 19) -> None:
        super().__init__()
        self.setFixedSize(size, size)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setPixmap(icons.pixmap(name, size=glyph, color=accent))
        tint = qcolor(accent, 30)
        self.setStyleSheet(
            f"background-color: rgba({tint.red()},{tint.green()},{tint.blue()},{tint.alpha()}); "
            f"border-radius: {max(8, size // 3)}px;"
        )


class TrendChip(QLabel):
    """趋势胶囊。用箭头与颜色表达环比变化。"""

    def __init__(self) -> None:
        super().__init__()
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setVisible(False)

    def apply(self, text: str, *, direction: int) -> None:
        if not text:
            self.setVisible(False)
            return
        if direction > 0:
            color, bg, arrow = Color.SUCCESS, Color.SUCCESS_SOFT, "↑"
        elif direction < 0:
            color, bg, arrow = Color.DANGER, Color.DANGER_SOFT, "↓"
        else:
            color, bg, arrow = Color.TEXT_MUTED, Color.SURFACE_SUBTLE, "·"
        self.setText(f"{arrow} {text}")
        self.setStyleSheet(
            f"background-color: {bg}; color: {color}; border-radius: 8px; "
            f"padding: 2px 8px; font-size: 12px; font-weight: 650;"
        )
        self.setVisible(True)


class StatTile(Card):
    """指标卡：图标 + 说明 + 大数字 + 趋势。"""

    def __init__(
        self,
        caption: str,
        value: str = "—",
        *,
        accent: str = Color.PRIMARY,
        glyph: str = "activity",
    ) -> None:
        super().__init__(padding=18, radius=RADIUS_LG)
        self.body().setSpacing(14)

        head = QHBoxLayout()
        head.setSpacing(10)
        head.addWidget(IconBadge(glyph, accent=accent))
        cap = faint(caption)
        cap.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        head.addWidget(cap, 1)
        self.add_layout(head)

        row = QHBoxLayout()
        row.setSpacing(8)
        self._value = label(value, object_name="Metric")
        row.addWidget(self._value)
        row.addStretch(1)
        self.trend = TrendChip()
        row.addWidget(self.trend, 0, Qt.AlignmentFlag.AlignBottom)
        self.add_layout(row)

    def set_value(self, value: str) -> None:
        self._value.setText(value)


class SectionHeader(QWidget):
    """区块标题 + 右侧可选操作。"""

    def __init__(self, title: str, *, action: QPushButton | None = None, hint: str = "") -> None:
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        row.addWidget(h2(title))
        if hint:
            row.addWidget(faint(hint))
        row.addStretch(1)
        if action is not None:
            row.addWidget(action)


class ListRow(Panel):
    """可点击的列表行。hover 有明确反馈，右侧带前进箭头。"""

    def __init__(self, *, on_click: Callable[[], None] | None = None, padding: int = 14) -> None:
        super().__init__(object_name="ListRow")
        self._on_click = on_click
        self._hover = False
        self.row = QHBoxLayout(self)
        self.row.setContentsMargins(padding, padding, padding, padding)
        self.row.setSpacing(14)
        if on_click is not None:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._render()

    def _render(self) -> None:
        bg = Color.SURFACE_HOVER if self._hover else Color.SURFACE
        border = Color.BORDER_STRONG if self._hover else Color.BORDER
        self.setStyleSheet(
            f"#ListRow {{ background: {bg}; border: 1px solid {border}; "
            f"border-radius: {RADIUS}px; }}"
        )

    def enterEvent(self, event) -> None:
        self._hover = True
        self._render()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover = False
        self._render()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if self._on_click is not None:
            self._on_click()
        super().mousePressEvent(event)

    def add_arrow(self) -> None:
        arrow = QLabel()
        arrow.setPixmap(icons.pixmap("chevron_right", size=18, color=Color.TEXT_FAINT))
        self.row.addWidget(arrow)


def icon_button(
    name: str,
    text: str = "",
    on_click: Callable[[], None] | None = None,
    *,
    kind: str = "Ghost",
    accent: str | None = None,
    glyph: int = 17,
) -> QPushButton:
    """带图标的按钮。kind 对应样式表里的 Primary / Ghost / Danger。"""
    btn = QPushButton(text)
    btn.setObjectName(kind)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setMinimumHeight(40)
    tone = accent or (Color.TEXT_ON_PRIMARY if kind in {"Primary", "Danger"} else Color.TEXT_MUTED)
    btn.setIcon(icons.icon(name, size=glyph, color=tone))
    btn.setIconSize(icons.icon_size(glyph))
    if on_click is not None:
        btn.clicked.connect(on_click)
    return btn


class TextButton(QPushButton):
    def __init__(self, text: str, on_click: Callable[[], None] | None = None) -> None:
        super().__init__(text)
        self.setObjectName("Link")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        if on_click is not None:
            self.clicked.connect(on_click)


def primary_button(text: str, on_click: Callable[[], None] | None = None) -> QPushButton:
    btn = QPushButton(text)
    btn.setObjectName("Primary")
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setMinimumHeight(40)
    if on_click is not None:
        btn.clicked.connect(on_click)
    return btn


def ghost_button(text: str, on_click: Callable[[], None] | None = None) -> QPushButton:
    btn = QPushButton(text)
    btn.setObjectName("Ghost")
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setMinimumHeight(40)
    if on_click is not None:
        btn.clicked.connect(on_click)
    return btn


def danger_button(text: str, on_click: Callable[[], None] | None = None) -> QPushButton:
    btn = QPushButton(text)
    btn.setObjectName("Danger")
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setMinimumHeight(40)
    if on_click is not None:
        btn.clicked.connect(on_click)
    return btn


class EmptyState(Card):
    """空态卡片：图标底衬 + 主文案 + 提示 + 可选操作。

    空态必须是"一块有边界的内容"而不是漂在空白里的文字，
    所以继承 Card 拿到白底与描边。
    """

    def __init__(
        self,
        title: str,
        hint: str = "",
        *,
        action: QPushButton | None = None,
        glyph: str = "layers",
        accent: str = Color.PRIMARY,
        tips: list[str] | None = None,
    ) -> None:
        super().__init__(padding=44)
        self.body().setSpacing(12)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumHeight(340)

        self.body().addStretch(1)
        art = IconBadge(glyph, accent=accent, size=64, glyph=30)
        self.body().addWidget(art, 0, Qt.AlignmentFlag.AlignHCenter)

        head = label(title, object_name="H2", align=Qt.AlignmentFlag.AlignCenter)
        self.body().addWidget(head)

        if hint:
            tip = muted(hint, wrap=True)
            tip.setAlignment(Qt.AlignmentFlag.AlignCenter)
            tip.setMaximumWidth(460)
            self.body().addWidget(tip, 0, Qt.AlignmentFlag.AlignHCenter)

        if tips:
            box = QVBoxLayout()
            box.setSpacing(8)
            for item in tips:
                line = QHBoxLayout()
                line.setSpacing(10)
                dot = QLabel()
                dot.setPixmap(icons.pixmap("check", size=15, color=accent))
                line.addWidget(dot, 0, Qt.AlignmentFlag.AlignTop)
                text = faint(item, wrap=True)
                text.setMaximumWidth(420)
                line.addWidget(text, 1)
                box.addLayout(line)
            wrap = QWidget()
            wrap.setLayout(box)
            self.body().addWidget(wrap, 0, Qt.AlignmentFlag.AlignHCenter)

        if action is not None:
            self.body().addSpacing(4)
            self.body().addWidget(action, 0, Qt.AlignmentFlag.AlignHCenter)
        self.body().addStretch(1)


def row(*widgets: QWidget, spacing: int = 12, stretch_last: bool = False) -> QHBoxLayout:
    layout = QHBoxLayout()
    layout.setSpacing(spacing)
    for i, widget in enumerate(widgets):
        stretch = 1 if (stretch_last and i == len(widgets) - 1) else 0
        layout.addWidget(widget, stretch)
    return layout


def scroll_friendly(widget: QWidget) -> QWidget:
    widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    return widget


def shadow(widget: QWidget, *, blur: int = 24, alpha: int = 80) -> None:
    """投影特效在打包环境下易触发崩溃，改用边框+抬升背景表达层次，此处保留空实现兼容调用。"""
    return
