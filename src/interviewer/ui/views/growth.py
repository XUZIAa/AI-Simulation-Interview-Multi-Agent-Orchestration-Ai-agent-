from __future__ import annotations

from datetime import datetime

from PySide6.QtWidgets import QHBoxLayout, QScrollArea, QVBoxLayout, QWidget

from ...app.async_utils import spawn
from ...app.context import AppContext
from ...core.types import ScoreDimension
from ...data.repositories.review_repo import TrendPoint
from ..navigation import Navigator, Page
from ..theme import Color
from ..widgets.charts import LineChart, TrendSeries, dimension_color
from ..widgets.common import (
    Card,
    EmptyState,
    faint,
    h3,
    icon_button,
    lead,
    page_title,
)


def _labels(points: list[TrendPoint]) -> list[str]:
    out = []
    for p in points:
        when = p.recorded_at.astimezone().strftime("%m-%d") if isinstance(p.recorded_at, datetime) else ""
        out.append(when)
    return out


class GrowthView(QWidget):
    def __init__(self, context: AppContext, nav: Navigator) -> None:
        super().__init__()
        self._ctx = context
        self._nav = nav
        self._build()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)
        host = QWidget()
        self._body = QVBoxLayout(host)
        self._body.setContentsMargins(36, 30, 36, 30)
        self._body.setSpacing(18)
        scroll.setWidget(host)

        head = QVBoxLayout()
        head.setSpacing(4)
        head.addWidget(page_title("成长轨迹"))
        head.addWidget(lead("从第一次模拟到最近一场，看着分数一点点涨起来。"))
        self._body.addLayout(head)

        self._content = QVBoxLayout()
        self._content.setSpacing(18)
        self._body.addLayout(self._content, 1)

    def on_show(self) -> None:
        spawn(self._load(), context="加载成长轨迹")

    async def _load(self) -> None:
        overall = await self._ctx.reviews.overall_series()
        dims = await self._ctx.reviews.dimension_series()
        self._render(overall, dims)

    def _render(self, overall: list[TrendPoint], dims: dict[ScoreDimension, list[TrendPoint]]) -> None:
        while self._content.count():
            item = self._content.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
            elif item.layout() is not None:
                self._drop(item.layout())

        if len(overall) < 1:
            self._content.addWidget(
                EmptyState(
                    "还没有成长数据",
                    "完成一场面试并生成复盘后，这里会画出你的分数曲线。",
                    glyph="growth",
                    tips=[
                        "综合得分曲线：看总体水平是否在往上走",
                        "各维度趋势：技术深度、逻辑表达、抗压能力分别追踪",
                        "同一岗位多次模拟，曲线对比才有意义",
                    ],
                    action=icon_button(
                        "play", "开始一场面试", lambda: self._nav.navigate(Page.PREPARE), kind="Primary"
                    ),
                ),
                1,
            )
            return

        trend_card = Card()
        trend_card.add(h3("综合得分曲线"))
        latest = overall[-1].score
        first = overall[0].score
        delta = latest - first
        arrow = "↑" if delta >= 0 else "↓"
        color = Color.SUCCESS if delta >= 0 else Color.DANGER
        summary = faint(
            f"最近 {latest:.0f} 分　·　共 {len(overall)} 场　·　较首场 {arrow}{abs(delta):.0f}"
        )
        summary.setStyleSheet(f"color: {color}; font-size: 13px;")
        trend_card.add(summary)
        overall_chart = LineChart()
        overall_chart.setMinimumHeight(260)
        overall_chart.set_data(
            [TrendSeries(name="综合", points=[p.score for p in overall], color=Color.PRIMARY)],
            _labels(overall),
        )
        trend_card.add(overall_chart)
        self._content.addWidget(trend_card)

        if dims:
            dim_card = Card()
            dim_card.add(h3("各维度趋势"))
            legend = QHBoxLayout()
            legend.setSpacing(14)
            series: list[TrendSeries] = []
            labels: list[str] = []
            for i, dim in enumerate(ScoreDimension):
                points = dims.get(dim)
                if not points:
                    continue
                color = dimension_color(i)
                series.append(TrendSeries(name=dim.label, points=[p.score for p in points], color=color))
                labels = _labels(points)
                legend.addWidget(self._legend_dot(dim.label, color))
            legend.addStretch(1)
            dim_card.add_layout(legend)
            dim_chart = LineChart()
            dim_chart.setMinimumHeight(280)
            dim_chart.set_data(series, labels)
            dim_card.add(dim_chart)
            self._content.addWidget(dim_card)
        self._content.addStretch(1)

    def _legend_dot(self, text: str, color: str) -> QWidget:
        wrap = QWidget()
        row = QHBoxLayout(wrap)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        dot = faint("●")
        dot.setStyleSheet(f"color: {color}; font-size: 12px;")
        label = faint(text)
        row.addWidget(dot)
        row.addWidget(label)
        return wrap

    def _drop(self, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
            elif item.layout() is not None:
                self._drop(item.layout())
