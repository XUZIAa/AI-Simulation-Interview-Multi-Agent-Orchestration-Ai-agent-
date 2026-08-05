from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import QWidget

from ..theme import Color, qcolor


class VoiceBars(QWidget):
    """一排随音量起伏的竖条，用作发言人的实时音量指示。"""

    def __init__(
        self,
        *,
        bars: int = 5,
        color: str = Color.CANDIDATE,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._color = color
        self._count = bars
        self._level = 0.0
        self._phase = 0.0
        self.setMinimumSize(64, 28)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(50)

    def set_level(self, level: float) -> None:
        self._level = max(0.0, min(1.0, level))

    def set_color(self, color: str) -> None:
        self._color = color
        self.update()

    def _tick(self) -> None:
        self._phase += 0.35
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        w, h = self.width(), self.height()
        gap = 4
        bar_w = (w - gap * (self._count - 1)) / self._count
        for i in range(self._count):
            wave = 0.5 + 0.5 * math.sin(self._phase + i * 0.9)
            amp = self._level * wave
            bar_h = max(3.0, amp * h)
            x = i * (bar_w + gap)
            y = (h - bar_h) / 2
            alpha = int(120 + 135 * min(1.0, amp * 1.4))
            painter.setBrush(QBrush(qcolor(self._color, alpha)))
            painter.drawRoundedRect(QRectF(x, y, bar_w, bar_h), bar_w / 2, bar_w / 2)
        painter.end()


class PulseOrb(QWidget):
    """面试官的发言光球。说话时脉动，静默时收敛。"""

    def __init__(self, *, color: str = Color.INTERVIEWER, size: int = 132) -> None:
        super().__init__()
        self._color = color
        self._level = 0.0
        self._active = False
        self._phase = 0.0
        self.setFixedSize(size, size)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(40)

    def set_level(self, level: float) -> None:
        self._level = max(0.0, min(1.0, level))

    def set_active(self, active: bool) -> None:
        self._active = active

    def _tick(self) -> None:
        self._phase += 0.08
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        center = QPointF(self.width() / 2, self.height() / 2)
        base = min(self.width(), self.height()) / 2 - 12
        breathe = 0.5 + 0.5 * math.sin(self._phase)
        pulse = base * (0.62 + 0.14 * breathe + 0.24 * self._level)

        halo = QRadialGradient(center, pulse * 1.7)
        halo.setColorAt(0.0, qcolor(self._color, 90))
        halo.setColorAt(1.0, qcolor(self._color, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(halo))
        painter.drawEllipse(center, pulse * 1.7, pulse * 1.7)

        core = QRadialGradient(center, pulse)
        top = QColor(self._color).lighter(125)
        core.setColorAt(0.0, qcolor(top.name(), 255))
        core.setColorAt(1.0, qcolor(self._color, 220))
        painter.setBrush(QBrush(core))
        painter.drawEllipse(center, pulse, pulse)

        ring = qcolor(Color.TEXT_ON_PRIMARY, 40 if self._active else 18)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(ring, 2))
        painter.drawEllipse(center, pulse + 6, pulse + 6)
        painter.end()
