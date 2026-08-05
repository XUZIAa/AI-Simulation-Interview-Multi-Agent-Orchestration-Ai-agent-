from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ...app.async_utils import spawn
from ...app.context import AppContext
from ...core.types import GapSeverity
from ...data.repositories.review_repo import StoredMistake
from ...report import export_mistakes_pdf
from ..navigation import Navigator, Page
from ..theme import Color
from ..widgets.common import (
    Badge,
    Card,
    EmptyState,
    faint,
    ghost_button,
    icon_button,
    lead,
    page_title,
)
from .review import _open_file

_SEVERITY_COLOR = {
    GapSeverity.BLOCKER: Color.DANGER,
    GapSeverity.MAJOR: Color.WARNING,
    GapSeverity.MINOR: Color.TEXT_FAINT,
}


class MistakeCard(Card):
    def __init__(self, stored: StoredMistake, on_toggle, on_delete) -> None:
        super().__init__(padding=16)
        self.body().setSpacing(6)
        item = stored.item
        top = QHBoxLayout()
        name = QLabel(item.knowledge_point)
        name.setWordWrap(True)
        name.setStyleSheet(f"color: {Color.TEXT}; font-size: 15px; font-weight: 600;")
        top.addWidget(name, 1)
        if stored.hit_count > 1:
            top.addWidget(Badge(f"错 {stored.hit_count} 次", color=Color.DANGER))
        top.addWidget(Badge(item.severity.label, color=_SEVERITY_COLOR.get(item.severity, Color.WARNING)))
        self.add_layout(top)

        meta = []
        if item.topic:
            meta.append(item.topic)
        if meta:
            self.add(faint("　·　".join(meta)))
        if item.question:
            self.add(self._text(f"题目：{item.question}", Color.TEXT_MUTED))
        if item.review_hint:
            self.add(self._text(f"复习要点：{item.review_hint}", Color.ACCENT))
        for point in item.key_points[:5]:
            self.add(self._text(f"· {point}", Color.TEXT_FAINT))

        actions = QHBoxLayout()
        actions.addStretch(1)
        toggle_text = "取消掌握" if stored.mastered else "标记为已掌握"
        actions.addWidget(ghost_button(toggle_text, lambda: on_toggle(stored)))
        actions.addWidget(icon_button("trash", "删除", lambda: on_delete(stored)))
        self.add_layout(actions)

    def _text(self, text: str, color: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(f"color: {color}; font-size: 13px;")
        return lbl


class MistakesView(QWidget):
    def __init__(self, context: AppContext, nav: Navigator) -> None:
        super().__init__()
        self._ctx = context
        self._nav = nav
        self._items: list[StoredMistake] = []
        self._build()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(36, 30, 36, 12)
        outer.setSpacing(16)

        header = QHBoxLayout()
        col = QVBoxLayout()
        col.setSpacing(4)
        col.addWidget(page_title("错题本"))
        self._subtitle = lead("历次面试答得不好的知识点会自动汇聚到这里。")
        col.addWidget(self._subtitle)
        header.addLayout(col, 1)
        self._export_btn = icon_button("download", "导出 PDF", self._export, kind="Primary")
        self._export_btn.setFixedWidth(140)
        header.addWidget(self._export_btn, 0, Qt.AlignmentFlag.AlignTop)
        outer.addLayout(header)

        filters = QHBoxLayout()
        filters.setSpacing(10)
        self._topic = QComboBox()
        self._topic.setFixedWidth(200)
        self._topic.currentIndexChanged.connect(lambda _: self._reload())
        self._scope = QComboBox()
        self._scope.addItem("仅未掌握", False)
        self._scope.addItem("全部（含已掌握）", True)
        self._scope.currentIndexChanged.connect(lambda _: self._reload())
        filters.addWidget(QLabel("主题"))
        filters.addWidget(self._topic)
        filters.addWidget(self._scope)
        filters.addStretch(1)
        outer.addLayout(filters)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        host = QWidget()
        self._list = QVBoxLayout(host)
        self._list.setContentsMargins(0, 0, 8, 0)
        self._list.setSpacing(12)
        self._list.addStretch(1)
        scroll.setWidget(host)
        outer.addWidget(scroll, 1)

    def on_show(self) -> None:
        spawn(self._load_topics(), context="加载错题主题")
        self._reload()

    async def _load_topics(self) -> None:
        topics = await self._ctx.reviews.topics()
        current = self._topic.currentData()
        self._topic.blockSignals(True)
        self._topic.clear()
        self._topic.addItem("全部主题", "")
        for topic in topics:
            self._topic.addItem(topic, topic)
        idx = self._topic.findData(current)
        self._topic.setCurrentIndex(max(0, idx))
        self._topic.blockSignals(False)

    def _reload(self) -> None:
        spawn(self._load(), context="加载错题")

    async def _load(self) -> None:
        topic = self._topic.currentData() or ""
        include = bool(self._scope.currentData())
        self._items = await self._ctx.reviews.list_mistakes(include_mastered=include, topic=topic)
        pending, mastered = await self._ctx.reviews.mistake_counts()
        self._subtitle.setText(f"待复习 {pending} 条　·　已掌握 {mastered} 条")
        self._render()

    def _render(self) -> None:
        # 整体清空后按分支重建，避免残留伸缩项与末尾条目错位
        while self._list.count():
            item = self._list.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        if not self._items:
            self._list.addWidget(
                EmptyState(
                    "还没有错题",
                    "面试中答得不好的知识点会自动汇总到这里，形成你的专属复习清单。",
                    glyph="mistakes",
                    accent=Color.WARNING,
                    tips=[
                        "同一知识点反复答错会累计次数，优先复习高频项",
                        "掌握之后可以标记，清单只留还没拿下的",
                        "支持一键导出 PDF，手机上随时翻",
                    ],
                    action=icon_button(
                        "play", "开始一场面试", lambda: self._nav.navigate(Page.PREPARE), kind="Primary"
                    ),
                ),
                1,
            )
            self._export_btn.setEnabled(False)
            return
        self._export_btn.setEnabled(True)
        for stored in self._items:
            self._list.addWidget(MistakeCard(stored, self._toggle, self._delete))
        self._list.addStretch(1)

    def _toggle(self, stored: StoredMistake) -> None:
        spawn(self._do_toggle(stored), context="更新掌握状态")

    async def _do_toggle(self, stored: StoredMistake) -> None:
        await self._ctx.reviews.set_mastered(stored.id, not stored.mastered)
        await self._load()

    def _delete(self, stored: StoredMistake) -> None:
        spawn(self._do_delete(stored.id), context="删除错题")

    async def _do_delete(self, mistake_id: int) -> None:
        await self._ctx.reviews.delete_mistake(mistake_id)
        await self._load()

    def _export(self) -> None:
        if not self._items:
            return
        try:
            path = export_mistakes_pdf(self._items)
        except Exception as exc:
            self._nav.toast(f"导出失败：{exc}", kind="error")
            return
        self._nav.toast("错题本已导出，正在打开", kind="success")
        _open_file(path)
