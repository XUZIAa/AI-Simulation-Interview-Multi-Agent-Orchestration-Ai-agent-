from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ...core.types import Speaker
from ..theme import Color


class _Bubble(QFrame):
    def __init__(self, speaker: Speaker, text: str, *, ghost: bool = False) -> None:
        super().__init__()
        mine = speaker is Speaker.CANDIDATE
        accent = Color.CANDIDATE if mine else Color.INTERVIEWER
        bg = Color.CANDIDATE_SOFT if mine else Color.INTERVIEWER_SOFT
        border = Color.BORDER if ghost else Color.BORDER_STRONG
        self.setStyleSheet(
            f"QFrame {{ background: {bg}; border: 1px solid {border}; "
            f"border-radius: 14px; }}"
        )
        box = QVBoxLayout(self)
        box.setContentsMargins(14, 9, 14, 10)
        box.setSpacing(3)
        name = QLabel(speaker.label + ("  ·  正在说" if ghost else ""))
        name.setStyleSheet(f"color: {accent}; font-size: 11px; font-weight: 700; border: none;")
        self._body = QLabel(text)
        self._body.setWordWrap(True)
        color = Color.TEXT if not ghost else Color.TEXT_MUTED
        self._body.setStyleSheet(f"color: {color}; font-size: 14px; border: none; background: transparent;")
        box.addWidget(name)
        box.addWidget(self._body)
        self.setMaximumWidth(560)

    def set_text(self, text: str) -> None:
        self._body.setText(text)


class TranscriptView(QScrollArea):
    """实时逐字稿。面试官靠左、我方靠右，未定稿的部分显示为浅色气泡。"""

    def __init__(self) -> None:
        super().__init__()
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        host = QWidget()
        self._layout = QVBoxLayout(host)
        self._layout.setContentsMargins(6, 6, 12, 6)
        self._layout.setSpacing(10)
        self._layout.addStretch(1)
        self.setWidget(host)
        self._ghost: QWidget | None = None
        self._ghost_bubble: _Bubble | None = None
        self._ghost_speaker: Speaker | None = None

    def _wrap(self, bubble: _Bubble, speaker: Speaker) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        if speaker is Speaker.CANDIDATE:
            layout.addStretch(1)
            layout.addWidget(bubble)
        else:
            layout.addWidget(bubble)
            layout.addStretch(1)
        return row

    def set_partial(self, speaker: Speaker, text: str) -> None:
        if not text.strip():
            return
        if self._ghost is None or self._ghost_speaker is not speaker:
            self._clear_ghost()
            self._ghost_bubble = _Bubble(speaker, text, ghost=True)
            self._ghost_speaker = speaker
            self._ghost = self._wrap(self._ghost_bubble, speaker)
            self._layout.addWidget(self._ghost)
        elif self._ghost_bubble is not None:
            self._ghost_bubble.set_text(text)
        self._scroll_to_bottom()

    def commit(self, speaker: Speaker, text: str) -> None:
        if not text.strip():
            return
        self._clear_ghost()
        bubble = _Bubble(speaker, text)
        self._layout.addWidget(self._wrap(bubble, speaker))
        self._scroll_to_bottom()

    def _clear_ghost(self) -> None:
        if self._ghost is not None:
            self._ghost.setParent(None)
            self._ghost.deleteLater()
        self._ghost = None
        self._ghost_bubble = None
        self._ghost_speaker = None

    def clear(self) -> None:
        # 只摘除气泡，保留顶部的伸缩项，否则内容不再贴底且会残留最后一条
        for i in reversed(range(self._layout.count())):
            item = self._layout.itemAt(i)
            widget = item.widget() if item is not None else None
            if widget is not None:
                self._layout.takeAt(i)
                widget.setParent(None)
                widget.deleteLater()
        self._ghost = None
        self._ghost_bubble = None
        self._ghost_speaker = None

    def _scroll_to_bottom(self) -> None:
        QTimer.singleShot(10, lambda: self.verticalScrollBar().setValue(self.verticalScrollBar().maximum()))
