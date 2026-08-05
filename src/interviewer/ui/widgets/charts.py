from __future__ import annotations

import math
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import QWidget

from ..theme import DIMENSION_COLORS, FONT_FAMILY, Color, qcolor


@dataclass(slots=True)
class RadarAxis:
    label: str
    value: float  # 0~100


class RadarChart(QWidget):
    """多维能力雷达图。技术深度、逻辑表达、抗压等维度一目了然。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._axes: list[RadarAxis] = []
        self.setMinimumSize(280, 280)

    def set_axes(self, axes: list[RadarAxis]) -> None:
        self._axes = axes
        self.update()

    def paintEvent(self, event) -> None:
        if len(self._axes) < 3:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        side = min(self.width(), self.height())
        center = QPointF(self.width() / 2, self.height() / 2)
        radius = side / 2 - 46
        count = len(self._axes)
        step = 2 * math.pi / count

        self._draw_grid(painter, center, radius, count, step)
        self._draw_polygon(painter, center, radius, step)
        self._draw_labels(painter, center, radius, step)
        painter.end()

    def _angle(self, index: int, step: float) -> float:
        return -math.pi / 2 + index * step

    def _draw_grid(self, painter: QPainter, center: QPointF, radius: float, count: int, step: float) -> None:
        pen = QPen(qcolor(Color.BORDER_STRONG, 210), 1)
        painter.setPen(pen)
        for ring in range(1, 5):
            r = radius * ring / 4
            path = QPainterPath()
            for i in range(count):
                angle = self._angle(i, step)
                point = QPointF(center.x() + r * math.cos(angle), center.y() + r * math.sin(angle))
                if i == 0:
                    path.moveTo(point)
                else:
                    path.lineTo(point)
            path.closeSubpath()
            painter.drawPath(path)
        for i in range(count):
            angle = self._angle(i, step)
            outer = QPointF(center.x() + radius * math.cos(angle), center.y() + radius * math.sin(angle))
            painter.drawLine(center, outer)

    def _draw_polygon(self, painter: QPainter, center: QPointF, radius: float, step: float) -> None:
        path = QPainterPath()
        for i, axis in enumerate(self._axes):
            angle = self._angle(i, step)
            r = radius * max(0.0, min(100.0, axis.value)) / 100.0
            point = QPointF(center.x() + r * math.cos(angle), center.y() + r * math.sin(angle))
            if i == 0:
                path.moveTo(point)
            else:
                path.lineTo(point)
        path.closeSubpath()

        fill = qcolor(Color.PRIMARY, 60)
        painter.setBrush(QBrush(fill))
        painter.setPen(QPen(qcolor(Color.PRIMARY), 2))
        painter.drawPath(path)

        painter.setBrush(QBrush(qcolor(Color.PRIMARY)))
        painter.setPen(Qt.PenStyle.NoPen)
        for i, axis in enumerate(self._axes):
            angle = self._angle(i, step)
            r = radius * max(0.0, min(100.0, axis.value)) / 100.0
            point = QPointF(center.x() + r * math.cos(angle), center.y() + r * math.sin(angle))
            painter.drawEllipse(point, 3.5, 3.5)

    def _draw_labels(self, painter: QPainter, center: QPointF, radius: float, step: float) -> None:
        font = QFont(FONT_FAMILY.split(",")[0].strip('"'))
        font.setPixelSize(13)
        painter.setFont(font)
        for i, axis in enumerate(self._axes):
            angle = self._angle(i, step)
            r = radius + 22
            point = QPointF(center.x() + r * math.cos(angle), center.y() + r * math.sin(angle))
            rect = QRectF(point.x() - 60, point.y() - 12, 120, 24)
            painter.setPen(QPen(qcolor(Color.TEXT_MUTED)))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, f"{axis.label} {axis.value:.0f}")


@dataclass(slots=True)
class TrendSeries:
    name: str
    points: list[float]
    color: str = Color.PRIMARY


class LineChart(QWidget):
    """成长曲线。多条序列叠加，展示历次面试的分数走向。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._series: list[TrendSeries] = []
        self._labels: list[str] = []
        self.setMinimumHeight(240)

    def set_data(self, series: list[TrendSeries], labels: list[str] | None = None) -> None:
        self._series = series
        self._labels = labels or []
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        left, top, right, bottom = 44, 18, 16, 30
        plot = QRectF(left, top, self.width() - left - right, self.height() - top - bottom)

        self._draw_axes(painter, plot)
        max_points = max((len(s.points) for s in self._series), default=0)
        if max_points == 0:
            painter.setPen(QPen(qcolor(Color.TEXT_FAINT)))
            painter.drawText(plot, Qt.AlignmentFlag.AlignCenter, "暂无历史数据")
            painter.end()
            return
        for series in self._series:
            self._draw_series(painter, plot, series, max_points)
        self._draw_x_labels(painter, plot, max_points)
        painter.end()

    def _draw_axes(self, painter: QPainter, plot: QRectF) -> None:
        painter.setPen(QPen(qcolor(Color.BORDER_STRONG, 200), 1))
        font = QFont(FONT_FAMILY.split(",")[0].strip('"'))
        font.setPixelSize(11)
        painter.setFont(font)
        for tick in range(0, 101, 25):
            y = plot.bottom() - plot.height() * tick / 100
            painter.setPen(QPen(qcolor(Color.BORDER_STRONG, 170), 1))
            painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            painter.setPen(QPen(qcolor(Color.TEXT_FAINT)))
            painter.drawText(QRectF(0, y - 9, plot.left() - 6, 18), Qt.AlignmentFlag.AlignRight, str(tick))

    def _project(self, plot: QRectF, index: int, count: int, value: float) -> QPointF:
        span = max(1, count - 1)
        x = plot.left() + plot.width() * index / span
        y = plot.bottom() - plot.height() * max(0.0, min(100.0, value)) / 100
        return QPointF(x, y)

    def _draw_series(self, painter: QPainter, plot: QRectF, series: TrendSeries, count: int) -> None:
        if not series.points:
            return
        color = qcolor(series.color)
        points = [self._project(plot, i, count, v) for i, v in enumerate(series.points)]

        if len(points) >= 2:
            area = QPainterPath()
            area.moveTo(QPointF(points[0].x(), plot.bottom()))
            for point in points:
                area.lineTo(point)
            area.lineTo(QPointF(points[-1].x(), plot.bottom()))
            area.closeSubpath()
            gradient = QLinearGradient(plot.topLeft(), plot.bottomLeft())
            gradient.setColorAt(0.0, qcolor(series.color, 70))
            gradient.setColorAt(1.0, qcolor(series.color, 0))
            painter.setBrush(QBrush(gradient))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawPath(area)

        painter.setPen(QPen(color, 2.4))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        line = QPainterPath()
        line.moveTo(points[0])
        for point in points[1:]:
            line.lineTo(point)
        painter.drawPath(line)

        painter.setBrush(QBrush(color))
        painter.setPen(QPen(qcolor(Color.SURFACE), 2))
        for point in points:
            painter.drawEllipse(point, 4, 4)

    def _draw_x_labels(self, painter: QPainter, plot: QRectF, count: int) -> None:
        if not self._labels:
            return
        painter.setPen(QPen(qcolor(Color.TEXT_FAINT)))
        font = QFont(FONT_FAMILY.split(",")[0].strip('"'))
        font.setPixelSize(11)
        painter.setFont(font)
        stride = max(1, count // 6)
        for i in range(0, count, stride):
            if i >= len(self._labels):
                break
            point = self._project(plot, i, count, 0)
            painter.drawText(
                QRectF(point.x() - 40, plot.bottom() + 4, 80, 18),
                Qt.AlignmentFlag.AlignCenter,
                self._labels[i],
            )


class ScoreRing(QWidget):
    """环形总分。中间大字，弧长按分数比例。"""

    def __init__(self, parent: QWidget | None = None, *, size: int = 150) -> None:
        super().__init__(parent)
        self._score = 0.0
        self._ring = size
        self.setFixedSize(size, size)

    def set_score(self, score: float) -> None:
        self._score = max(0.0, min(100.0, score))
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        thickness = max(4, int(self._ring * 0.08))
        margin = thickness
        rect = QRectF(margin, margin, self.width() - 2 * margin, self.height() - 2 * margin)

        painter.setPen(QPen(qcolor(Color.SURFACE_ACTIVE), thickness, cap=Qt.PenCapStyle.RoundCap))
        painter.drawArc(rect, 0, 360 * 16)

        color = _score_color(self._score)
        span = int(-360 * 16 * self._score / 100)
        painter.setPen(QPen(qcolor(color), thickness, cap=Qt.PenCapStyle.RoundCap))
        painter.drawArc(rect, 90 * 16, span)

        painter.setPen(QPen(qcolor(Color.TEXT)))
        font = QFont(FONT_FAMILY.split(",")[0].strip('"'))
        font.setPixelSize(max(13, int(self._ring * 0.30)))
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, f"{self._score:.0f}")
        painter.end()


def _score_color(score: float) -> str:
    if score >= 80:
        return Color.SUCCESS
    if score >= 60:
        return Color.PRIMARY
    if score >= 45:
        return Color.WARNING
    return Color.DANGER


def dimension_color(index: int) -> str:
    return DIMENSION_COLORS[index % len(DIMENSION_COLORS)]


class SparkBar(QWidget):
    """迷你水平进度条，用于维度分、技能覆盖度等。"""

    def __init__(self, value: float = 0.0, *, color: str = Color.PRIMARY) -> None:
        super().__init__()
        self._value = value
        self._color = color
        self.setFixedHeight(8)
        self.setMinimumWidth(80)

    def set_value(self, value: float, *, color: str | None = None) -> None:
        self._value = max(0.0, min(100.0, value))
        if color:
            self._color = color
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        radius = self.height() / 2
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(qcolor(Color.BORDER)))
        painter.drawRoundedRect(QRectF(0, 0, self.width(), self.height()), radius, radius)
        width = self.width() * max(0.0, min(100.0, self._value)) / 100
        if width > 0:
            painter.setBrush(QBrush(qcolor(self._color)))
            painter.drawRoundedRect(QRectF(0, 0, width, self.height()), radius, radius)
        painter.end()
