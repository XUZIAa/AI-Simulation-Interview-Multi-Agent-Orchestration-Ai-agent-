from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ...app.async_utils import spawn
from ...app.context import AppContext
from ...core.events import ReviewProgress
from ...core.types import AnnotationKind, Speaker
from ...domain.interview import InterviewState, TurnRecord
from ...domain.review import ReviewReport
from ...report import export_review_pdf
from ..navigation import Navigator, Page
from ..theme import Color
from ..widgets.charts import RadarAxis, RadarChart, ScoreRing, SparkBar, dimension_color
from ..widgets.common import (
    Badge,
    Card,
    EmptyState,
    faint,
    h2,
    h3,
    icon_button,
    page_title,
)

logger = logging.getLogger(__name__)

_ANNOTATION_COLOR = {
    AnnotationKind.STRENGTH: Color.STRENGTH,
    AnnotationKind.WEAKNESS: Color.WEAKNESS,
    AnnotationKind.FILLER: Color.FILLER,
    AnnotationKind.OFF_TOPIC: Color.OFF_TOPIC,
}


def _open_file(path: Path) -> None:
    try:
        if sys.platform == "win32":
            os.startfile(str(path))
        elif sys.platform == "darwin":
            os.system(f'open "{path}"')
        else:
            os.system(f'xdg-open "{path}"')
    except Exception:
        logger.warning("无法打开文件 %s", path, exc_info=True)


class ReviewView(QWidget):
    def __init__(self, context: AppContext, nav: Navigator) -> None:
        super().__init__()
        self._ctx = context
        self._nav = nav
        self._session_id: int | None = None
        self._report: ReviewReport | None = None
        self._title = ""
        self._unsub = None
        self._build()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        bar = QHBoxLayout()
        bar.setContentsMargins(36, 24, 36, 8)
        self._back = icon_button(
            "chevron_left", "返回工作台", lambda: self._nav.navigate(Page.DASHBOARD)
        )
        self._back.setFixedWidth(140)
        bar.addWidget(self._back)
        bar.addStretch(1)
        self._export_btn = icon_button("download", "导出 PDF 报告", self._export, kind="Primary")
        self._export_btn.setFixedWidth(160)
        self._export_btn.setEnabled(False)
        bar.addWidget(self._export_btn)
        outer.addLayout(bar)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        outer.addWidget(self._scroll, 1)
        self._host = QWidget()
        self._body = QVBoxLayout(self._host)
        self._body.setContentsMargins(36, 12, 36, 30)
        self._body.setSpacing(18)
        self._scroll.setWidget(self._host)

    # ------------------------------------------------------------------

    def show_review(self, session_id: int, *, generate: bool = False) -> None:
        self._session_id = session_id
        self._report = None
        self._export_btn.setEnabled(False)
        self._clear()
        self._status = QLabel("正在准备复盘…")
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status.setStyleSheet(f"color: {Color.TEXT_MUTED}; font-size: 15px; padding: 60px;")
        self._body.addWidget(self._status)
        spawn(self._load(session_id, generate), context="加载复盘")

    async def _load(self, session_id: int, generate: bool) -> None:
        report = None if generate else await self._ctx.review.load(session_id)
        state = await self._ctx.sessions.load_state(session_id)
        self._title = self._title_from(state)
        if report is None:
            if state is None:
                self._status.setText("找不到这场面试的数据，无法生成复盘。")
                return
            if not state.reviewable:
                self._render_too_short()
                return
            if not generate:
                # 生成一份复盘要跑评分、批注、改写、错题、提升方案，别静默烧掉用户的额度
                self._render_generate_prompt(session_id)
                return
            self._listen_progress()
            try:
                report = await self._ctx.review.generate(state)
            finally:
                self._stop_progress()
        turns = await self._ctx.sessions.load_turns(session_id)
        self._report = report
        self._render(report, turns)

    def _title_from(self, state: InterviewState | None) -> str:
        if state is None:
            return "面试复盘"
        head = state.job_title or "综合面试"
        return f"{head}｜{state.persona.name}"

    def _listen_progress(self) -> None:
        self._unsub = self._ctx.bus.subscribe(ReviewProgress, self._on_progress)

    def _stop_progress(self) -> None:
        if self._unsub is not None:
            self._unsub()
            self._unsub = None

    def _on_progress(self, event: ReviewProgress) -> None:
        if self._status is not None:
            self._status.setText(f"{event.detail or '正在生成复盘'} … {event.percent}%")

    # ------------------------------------------------------------------

    def _render_too_short(self) -> None:
        self._clear()
        self._body.addWidget(
            EmptyState(
                "本场面试不足 5 分钟",
                "太短的面试不足以生成有价值的复盘。下次聊得久一点，我会给你完整的能力雷达和专项方案。",
                action=icon_button(
                "chevron_left", "返回工作台", lambda: self._nav.navigate(Page.DASHBOARD), kind="Primary"
            ),
                glyph="clock",
            )
        )

    def _render_generate_prompt(self, session_id: int) -> None:
        self._clear()
        self._body.addWidget(
            EmptyState(
                "这场面试还没生成复盘",
                "生成复盘会调用模型完成打分、逐字稿批注、满分答案重构与专项方案，需要一点时间和额度。",
                action=icon_button(
                    "sparkles",
                    "生成复盘",
                    lambda: self.show_review(session_id, generate=True),
                    kind="Primary",
                ),
                glyph="sparkles",
            )
        )

    def _render(self, report: ReviewReport, turns: list[TurnRecord]) -> None:
        self._clear()
        self._export_btn.setEnabled(True)
        self._body.addWidget(self._overview_card(report))
        self._body.addWidget(self._radar_card(report))
        if report.strengths or report.improvements:
            self._body.addWidget(self._highlights_card(report))
        if report.prosody.verdict:
            self._body.addWidget(self._prosody_card(report))
        if report.improvement_plans:
            self._body.addWidget(self._plans_card(report))
        if report.rewrites:
            self._body.addWidget(self._rewrites_card(report))
        if report.annotations:
            self._body.addWidget(self._transcript_card(report, turns))
        if report.mistakes:
            self._body.addWidget(self._mistakes_card(report))
        if report.next_actions:
            self._body.addWidget(self._next_card(report))
        self._body.addStretch(1)

    def _overview_card(self, report: ReviewReport) -> Card:
        card = Card()
        top = QHBoxLayout()
        top.setSpacing(20)
        ring = ScoreRing(size=150)
        ring.set_score(report.overall_score)
        top.addWidget(ring)
        col = QVBoxLayout()
        col.setSpacing(6)
        col.addWidget(page_title(self._title))
        headline = QLabel(report.headline or "面试复盘")
        headline.setWordWrap(True)
        headline.setStyleSheet(f"color: {Color.PRIMARY}; font-size: 16px; font-weight: 600;")
        col.addWidget(headline)
        if report.summary:
            summary = QLabel(report.summary)
            summary.setWordWrap(True)
            summary.setStyleSheet(f"color: {Color.TEXT_MUTED}; font-size: 14px;")
            col.addWidget(summary)
        col.addStretch(1)
        top.addLayout(col, 1)
        card.add_layout(top)
        return card

    def _radar_card(self, report: ReviewReport) -> Card:
        card = Card()
        card.add(h3("多维能力"))
        row = QHBoxLayout()
        row.setSpacing(24)
        radar = RadarChart()
        radar.set_axes([RadarAxis(label=d.dimension.label, value=d.score) for d in report.dimensions])
        radar.setMinimumSize(320, 320)
        row.addWidget(radar)

        bars = QVBoxLayout()
        bars.setSpacing(12)
        for i, dim in enumerate(report.dimensions):
            block = QVBoxLayout()
            block.setSpacing(4)
            head = QHBoxLayout()
            name = QLabel(dim.dimension.label)
            name.setStyleSheet(f"color: {Color.TEXT}; font-weight: 600;")
            score = QLabel(f"{dim.score:.0f}")
            score.setStyleSheet(f"color: {dimension_color(i)}; font-weight: 700;")
            head.addWidget(name)
            head.addStretch(1)
            head.addWidget(score)
            block.addLayout(head)
            bar = SparkBar(dim.score, color=dimension_color(i))
            block.addWidget(bar)
            if dim.reason:
                reason = QLabel(dim.reason)
                reason.setWordWrap(True)
                reason.setStyleSheet(f"color: {Color.TEXT_FAINT}; font-size: 12px;")
                block.addWidget(reason)
            bars.addLayout(block)
        row.addLayout(bars, 1)
        card.add_layout(row)
        return card

    def _highlights_card(self, report: ReviewReport) -> Card:
        card = Card()
        row = QHBoxLayout()
        row.setSpacing(20)
        row.addLayout(self._bullet_col("亮点", report.strengths, Color.SUCCESS), 1)
        row.addLayout(self._bullet_col("待改进", report.improvements, Color.WARNING), 1)
        card.add_layout(row)
        return card

    def _bullet_col(self, title: str, items: list[str], color: str) -> QVBoxLayout:
        col = QVBoxLayout()
        col.setSpacing(8)
        head = QLabel(title)
        head.setStyleSheet(f"color: {color}; font-size: 15px; font-weight: 700;")
        col.addWidget(head)
        for item in items:
            row = QHBoxLayout()
            row.setSpacing(8)
            dot = QLabel("•")
            dot.setStyleSheet(f"color: {color};")
            dot.setAlignment(Qt.AlignmentFlag.AlignTop)
            text = QLabel(item)
            text.setWordWrap(True)
            text.setStyleSheet(f"color: {Color.TEXT_MUTED}; font-size: 13px;")
            row.addWidget(dot)
            row.addWidget(text, 1)
            col.addLayout(row)
        col.addStretch(1)
        return col

    def _prosody_card(self, report: ReviewReport) -> Card:
        p = report.prosody
        card = Card()
        card.add(h3("情绪与语速"))
        chips = QHBoxLayout()
        chips.setSpacing(10)
        for text in (
            f"语速 {p.words_per_minute:.0f} 字/分",
            f"口头禅 每百字 {p.filler_ratio:.1f}",
            f"停顿占比 {p.pause_ratio * 100:.0f}%",
            f"被打断 {p.interrupted_count} 次",
        ):
            chips.addWidget(Badge(text, color=Color.ACCENT))
        chips.addStretch(1)
        card.add_layout(chips)
        verdict = QLabel(p.verdict)
        verdict.setWordWrap(True)
        verdict.setStyleSheet(f"color: {Color.TEXT_MUTED}; font-size: 14px;")
        card.add(verdict)
        return card

    def _plans_card(self, report: ReviewReport) -> Card:
        card = Card()
        card.add(h2("专项提升方案"))
        card.add(faint("针对本场暴露的短板，给出可执行的训练路径。"))
        for plan in report.improvement_plans:
            block = Card(elevated=False)
            block.body().setSpacing(6)
            block.add(h3(plan.focus_area))
            if plan.diagnosis:
                block.add(self._muted_text(f"诊断：{plan.diagnosis}"))
            if plan.expected_gain:
                block.add(self._muted_text(f"预期收益：{plan.expected_gain}", Color.SUCCESS))
            for drill in plan.drills:
                line = f"· {drill.action}"
                if drill.time_cost:
                    line += f"（{drill.time_cost}）"
                block.add(self._muted_text(line, Color.TEXT))
            if plan.resources:
                block.add(self._muted_text("推荐资料：" + "、".join(plan.resources)))
            if plan.next_mock_setup:
                block.add(self._muted_text(f"下次模拟：{plan.next_mock_setup}", Color.PRIMARY))
            card.add(block)
        return card

    def _rewrites_card(self, report: ReviewReport) -> Card:
        card = Card()
        card.add(h2("满分答案重构"))
        for rw in report.rewrites:
            block = Card(elevated=False)
            block.body().setSpacing(6)
            block.add(h3(rw.question))
            block.add(self._muted_text(f"你的回答：{rw.original}", Color.WEAKNESS))
            block.add(self._muted_text(f"满分示范：{rw.rewritten}", Color.SUCCESS))
            for why in rw.why_better:
                block.add(self._muted_text(f"· {why}", Color.TEXT_FAINT))
            card.add(block)
        return card

    def _transcript_card(self, report: ReviewReport, turns: list[TurnRecord]) -> Card:
        card = Card()
        card.add(h2("逐字稿高亮批注"))
        by_turn: dict[int, list] = {}
        for ann in report.annotations:
            by_turn.setdefault(ann.turn_index, []).append(ann)
        for turn in turns:
            anns = by_turn.get(turn.index, [])
            card.add(self._turn_row(turn, anns))
        return card

    def _turn_row(self, turn: TurnRecord, anns: list) -> QWidget:
        wrap = QWidget()
        layout = QVBoxLayout(wrap)
        layout.setContentsMargins(0, 0, 0, 6)
        layout.setSpacing(4)
        accent = _ANNOTATION_COLOR.get(anns[0].kind, Color.BORDER) if anns else Color.BORDER
        who = Color.CANDIDATE if turn.speaker is Speaker.CANDIDATE else Color.INTERVIEWER
        head = QLabel(turn.speaker.label)
        head.setStyleSheet(f"color: {who}; font-size: 12px; font-weight: 700;")
        layout.addWidget(head)
        text = QLabel(turn.text)
        text.setWordWrap(True)
        border = f"border-left: 3px solid {accent}; padding-left: 10px;" if anns else "padding-left: 13px;"
        text.setStyleSheet(f"color: {Color.TEXT}; font-size: 14px; {border}")
        layout.addWidget(text)
        for ann in anns:
            color = _ANNOTATION_COLOR.get(ann.kind, Color.PRIMARY)
            note = QLabel(f"◆ {ann.kind.label}：{ann.comment}")
            note.setWordWrap(True)
            note.setStyleSheet(f"color: {color}; font-size: 12px; padding-left: 13px;")
            layout.addWidget(note)
        return wrap

    def _mistakes_card(self, report: ReviewReport) -> Card:
        card = Card()
        top = QHBoxLayout()
        top.addWidget(h2("错题清单"), 1)
        top.addWidget(icon_button("mistakes", "查看错题本", lambda: self._nav.navigate(Page.MISTAKES)))
        card.add_layout(top)
        for m in report.mistakes:
            block = Card(elevated=False)
            block.body().setSpacing(4)
            head = QHBoxLayout()
            name = QLabel(m.knowledge_point)
            name.setStyleSheet(f"color: {Color.TEXT}; font-weight: 600;")
            head.addWidget(name, 1)
            head.addWidget(Badge(m.severity.label, color=Color.WARNING))
            block.add_layout(head)
            if m.review_hint:
                block.add(self._muted_text(m.review_hint))
            card.add(block)
        return card

    def _next_card(self, report: ReviewReport) -> Card:
        card = Card()
        card.add(h3("下一步行动"))
        for action in report.next_actions:
            card.add(self._muted_text(f"→ {action}", Color.TEXT))
        return card

    def _muted_text(self, text: str, color: str = Color.TEXT_MUTED) -> QLabel:
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(f"color: {color}; font-size: 13px;")
        return lbl

    # ------------------------------------------------------------------

    def _export(self) -> None:
        if self._report is None:
            return
        try:
            path = export_review_pdf(self._report, title=self._title)
        except Exception as exc:
            self._nav.toast(f"导出失败：{exc}", kind="error")
            return
        self._nav.toast("报告已导出，正在打开", kind="success")
        _open_file(path)

    def _clear(self) -> None:
        self._status = None
        while self._body.count():
            item = self._body.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
            elif item.layout() is not None:
                self._drop_layout(item.layout())

    def _drop_layout(self, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
            elif item.layout() is not None:
                self._drop_layout(item.layout())
