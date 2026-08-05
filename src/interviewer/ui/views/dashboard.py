from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ...app.async_utils import spawn
from ...app.context import AppContext
from ...core.types import SessionStatus
from ...data.repositories.review_repo import TrendPoint
from ...data.repositories.session_repo import GlobalStats, SessionSummary
from ...domain.persona import PersonaContract
from .. import icons
from ..navigation import Navigator, Page
from ..theme import Color
from ..widgets.charts import LineChart, ScoreRing, TrendSeries
from ..widgets.common import (
    Badge,
    Card,
    IconBadge,
    ListRow,
    SectionHeader,
    StatTile,
    TextButton,
    faint,
    h3,
    icon_button,
    lead,
    page_title,
)

_STATUS_COLOR: dict[SessionStatus, str] = {
    SessionStatus.DRAFT: Color.TEXT_FAINT,
    SessionStatus.RUNNING: Color.WARNING,
    SessionStatus.REVIEWING: Color.INFO,
    SessionStatus.COMPLETED: Color.SUCCESS,
    SessionStatus.ABORTED: Color.DANGER,
}

_ONBOARDING: tuple[tuple[str, str, str], ...] = (
    ("upload", "上传简历与目标 JD", "没有 JD 也行，填个岗位名就能一键生成"),
    ("persona", "挑一位面试官", "大厂、制造业、国企风格各不相同，也能自己调"),
    ("mic", "开口面试", "可随时打断，说得太久面试官也会打断你"),
)


class _SessionRow(ListRow):
    """一场面试的富文本行：分数环 + 标题 + 元信息 + 状态。"""

    def __init__(self, summary: SessionSummary, on_open) -> None:
        super().__init__(on_click=lambda: on_open(summary.id), padding=14)

        if summary.overall_score is not None:
            ring = ScoreRing(size=54)
            ring.set_score(summary.overall_score)
            self.row.addWidget(ring)
        else:
            self.row.addWidget(IconBadge("clock", accent=Color.TEXT_FAINT, size=44, glyph=20))

        col = QVBoxLayout()
        col.setSpacing(4)
        title = QLabel(summary.title)
        title.setStyleSheet(f"color: {Color.TEXT}; font-size: 15px; font-weight: 650;")
        col.addWidget(title)

        meta = QHBoxLayout()
        meta.setSpacing(14)
        for glyph, text in (
            ("user", summary.persona_name),
            ("calendar", _when(summary.created_at)),
            ("clock", f"{summary.duration_ms // 60000} 分钟"),
        ):
            meta.addLayout(_meta_item(glyph, text))
        meta.addStretch(1)
        col.addLayout(meta)
        self.row.addLayout(col, 1)

        self.row.addWidget(
            Badge(summary.status.label, color=_STATUS_COLOR.get(summary.status, Color.PRIMARY))
        )
        self.add_arrow()


class _PersonaRow(ListRow):
    """快速开始：直接从某位面试官进入准备流程。"""

    def __init__(self, contract: PersonaContract, on_pick) -> None:
        super().__init__(on_click=lambda: on_pick(contract), padding=11)
        self.row.setSpacing(11)
        self.row.addWidget(IconBadge("user", accent=Color.PRIMARY, size=32, glyph=17))
        col = QVBoxLayout()
        col.setSpacing(1)
        name = QLabel(contract.name)
        name.setStyleSheet(f"color: {Color.TEXT}; font-size: 13px; font-weight: 650;")
        tier = QLabel(contract.company_tier.label)
        tier.setStyleSheet(f"color: {Color.TEXT_FAINT}; font-size: 11px;")
        col.addWidget(name)
        col.addWidget(tier)
        self.row.addLayout(col, 1)
        self.add_arrow()


def _meta_item(glyph: str, text: str) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setSpacing(5)
    mark = QLabel()
    mark.setPixmap(icons.pixmap(glyph, size=13, color=Color.TEXT_FAINT))
    row.addWidget(mark)
    row.addWidget(faint(text))
    return row


def _when(value: datetime | None) -> str:
    if not isinstance(value, datetime):
        return "—"
    return value.astimezone().strftime("%m-%d %H:%M")


class DashboardView(QWidget):
    def __init__(self, context: AppContext, nav: Navigator) -> None:
        super().__init__()
        self._ctx = context
        self._nav = nav
        self._build()

    # ------------------------------------------------------------------
    # 构建
    # ------------------------------------------------------------------

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(scroll)

        host = QWidget()
        self._layout = QVBoxLayout(host)
        self._layout.setContentsMargins(38, 30, 38, 30)
        self._layout.setSpacing(22)
        scroll.setWidget(host)

        self._layout.addWidget(self._build_hero())
        self._layout.addLayout(self._build_stats())
        self._layout.addLayout(self._build_middle())
        self._layout.addWidget(
            SectionHeader(
                "最近面试",
                action=TextButton("全部错题 →", lambda: self._nav.navigate(Page.MISTAKES)),
            )
        )
        self._recent_box = QVBoxLayout()
        self._recent_box.setSpacing(10)
        self._layout.addLayout(self._recent_box)
        self._layout.addStretch(1)

    def _build_hero(self) -> QWidget:
        host = QWidget()
        row = QHBoxLayout(host)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(20)

        col = QVBoxLayout()
        col.setSpacing(6)
        col.addWidget(page_title("工作台"))
        col.addWidget(lead("准备好了就开始下一场模拟，每一场都会沉淀成你的成长轨迹。"))
        row.addLayout(col, 1)

        cta = icon_button("plus", "开始新面试", lambda: self._nav.navigate(Page.PREPARE), kind="Primary")
        cta.setMinimumWidth(158)
        cta.setMinimumHeight(44)
        row.addWidget(cta, 0, Qt.AlignmentFlag.AlignVCenter)
        return host

    def _build_stats(self) -> QGridLayout:
        grid = QGridLayout()
        grid.setSpacing(14)
        self._tiles = {
            "total": StatTile("累计面试", accent=Color.PRIMARY, glyph="dashboard"),
            "avg": StatTile("平均分", accent=Color.INFO, glyph="activity"),
            "best": StatTile("历史最高分", accent=Color.WARNING, glyph="award"),
            "minutes": StatTile("累计时长", accent=Color.ACCENT, glyph="clock"),
        }
        for i, tile in enumerate(self._tiles.values()):
            grid.addWidget(tile, 0, i)
            grid.setColumnStretch(i, 1)
        return grid

    def _build_middle(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(16)

        trend_card = Card(padding=20)
        trend_card.add_layout(_card_head("growth", "分数走势", Color.PRIMARY))
        self._trend = LineChart()
        self._trend.setMinimumHeight(212)
        trend_card.add(self._trend)
        row.addWidget(trend_card, 2)

        quick = Card(padding=18)
        quick.body().setSpacing(10)
        quick.add_layout(_card_head("zap", "快速开始", Color.WARNING))
        self._quick_box = QVBoxLayout()
        self._quick_box.setSpacing(8)
        quick.add_layout(self._quick_box)
        quick.body().addStretch(1)
        quick.setMinimumWidth(268)
        row.addWidget(quick, 1)
        return row

    # ------------------------------------------------------------------
    # 数据
    # ------------------------------------------------------------------

    def on_show(self) -> None:
        spawn(self._load(), context="加载工作台")

    async def _load(self) -> None:
        stats = await self._ctx.sessions.stats()
        self._render_stats(stats)
        recent = await self._ctx.sessions.list_recent(limit=20)
        self._render_recent(recent)
        series = await self._ctx.reviews.overall_series(limit=12)
        self._render_trend(series)
        personas = await self._ctx.personas.list_all()
        self._render_quick(personas)

    def _render_stats(self, stats: GlobalStats) -> None:
        self._tiles["total"].set_value(str(stats.total_sessions))
        done = stats.completed_sessions
        if stats.total_sessions:
            self._tiles["total"].trend.apply(f"已完成 {done}", direction=0)

        self._tiles["avg"].set_value(f"{stats.average_score:.0f}" if stats.average_score else "—")
        if stats.average_score and stats.latest_score:
            delta = stats.latest_score - stats.average_score
            sign = "+" if delta >= 0 else ""
            self._tiles["avg"].trend.apply(
                f"最近 {sign}{delta:.0f}", direction=1 if delta > 0 else (-1 if delta < 0 else 0)
            )

        self._tiles["best"].set_value(f"{stats.best_score:.0f}" if stats.best_score else "—")
        self._tiles["minutes"].set_value(_duration(stats.total_minutes))

    def _render_trend(self, series: list[TrendPoint]) -> None:
        if len(series) < 2:
            self._trend.set_data([], [])
            return
        points = [p.score for p in series]
        labels = [p.recorded_at.astimezone().strftime("%m-%d") for p in series]
        self._trend.set_data([TrendSeries(name="综合得分", points=points, color=Color.PRIMARY)], labels)

    def _render_quick(self, personas: list[PersonaContract]) -> None:
        _clear(self._quick_box)
        for contract in personas[:4]:
            self._quick_box.addWidget(_PersonaRow(contract, self._pick_persona))
        if not personas:
            self._quick_box.addWidget(faint("还没有可用的面试官人设"))

    def _render_recent(self, recent: list[SessionSummary]) -> None:
        _clear(self._recent_box)
        if not recent:
            self._recent_box.addWidget(self._build_onboarding())
            return
        for summary in recent:
            self._recent_box.addWidget(_SessionRow(summary, self._open))

    def _build_onboarding(self) -> QWidget:
        card = Card(padding=26)
        card.body().setSpacing(16)
        card.add(h3("三步开始你的第一场模拟"))
        for i, (glyph, title, hint) in enumerate(_ONBOARDING, start=1):
            row = QHBoxLayout()
            row.setSpacing(14)
            row.addWidget(IconBadge(glyph, accent=Color.PRIMARY, size=38, glyph=19))
            col = QVBoxLayout()
            col.setSpacing(2)
            head = QLabel(f"{i}. {title}")
            head.setStyleSheet(f"color: {Color.TEXT}; font-size: 14px; font-weight: 650;")
            col.addWidget(head)
            col.addWidget(faint(hint))
            row.addLayout(col, 1)
            card.add_layout(row)
        cta = icon_button("play", "去准备面试", lambda: self._nav.navigate(Page.PREPARE), kind="Primary")
        cta.setMinimumWidth(150)
        foot = QHBoxLayout()
        foot.addWidget(cta)
        foot.addStretch(1)
        card.add_layout(foot)
        return card

    # ------------------------------------------------------------------

    def _open(self, session_id: int) -> None:
        self._nav.open_review(session_id)

    def _pick_persona(self, contract: PersonaContract) -> None:
        self._nav.open_prepare(persona=contract)


def _card_head(glyph: str, title: str, accent: str) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setSpacing(10)
    row.addWidget(IconBadge(glyph, accent=accent, size=30, glyph=16))
    row.addWidget(h3(title), 1)
    return row


def _duration(minutes: int) -> str:
    if minutes < 60:
        return f"{minutes} 分"
    return f"{minutes / 60:.1f} 小时"


def _clear(box: QVBoxLayout) -> None:
    while box.count():
        item = box.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.deleteLater()
