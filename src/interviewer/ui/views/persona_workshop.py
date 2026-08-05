from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QScrollArea,
    QSlider,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ...app.async_utils import spawn
from ...app.context import AppContext
from ...core.providers_catalog import VOICE_LABELS
from ...core.types import CompanyTier
from ...domain.persona import (
    PersonaArchetype,
    PersonaContract,
    PressureProfile,
    ProbingProfile,
    SpeechStyle,
)
from ..navigation import Navigator
from ..theme import Color
from ..widgets.common import (
    Badge,
    Card,
    Divider,
    Panel,
    combo_enum,
    faint,
    h3,
    icon_button,
    lead,
    page_title,
)


class _Slider(QWidget):
    def __init__(self, caption: str, value: int, hint: str = "") -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        cap = QLabel(caption)
        cap.setFixedWidth(96)
        cap.setStyleSheet(f"color: {Color.TEXT_MUTED};")
        cap.setToolTip(hint)
        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setRange(0, 10)
        self._slider.setValue(value)
        self._readout = QLabel(str(value))
        self._readout.setFixedWidth(24)
        self._readout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._readout.setStyleSheet(f"color: {Color.PRIMARY}; font-weight: 700;")
        self._slider.valueChanged.connect(lambda v: self._readout.setText(str(v)))
        layout.addWidget(cap)
        layout.addWidget(self._slider, 1)
        layout.addWidget(self._readout)

    def value(self) -> int:
        return self._slider.value()

    def set_value(self, value: int) -> None:
        self._slider.setValue(value)

    def on_change(self, fn) -> None:
        self._slider.valueChanged.connect(lambda _: fn())


class _PersonaItem(Panel):
    def __init__(self, contract: PersonaContract, on_click) -> None:
        super().__init__(object_name="PersonaItem")
        self.contract = contract
        self._on_click = on_click
        self._selected = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 11, 14, 11)
        layout.setSpacing(4)
        top = QHBoxLayout()
        name = QLabel(contract.name)
        name.setStyleSheet(f"color: {Color.TEXT}; font-size: 14px; font-weight: 600;")
        top.addWidget(name, 1)
        if contract.is_builtin:
            top.addWidget(Badge("内置", color=Color.TEXT_FAINT))
        layout.addLayout(top)
        sub = QLabel(f"{contract.archetype.label} · {contract.company_tier.label}")
        sub.setStyleSheet(f"color: {Color.TEXT_FAINT}; font-size: 12px;")
        layout.addWidget(sub)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._render()

    def set_selected(self, value: bool) -> None:
        self._selected = value
        self._render()

    def _render(self) -> None:
        border = Color.PRIMARY if self._selected else Color.BORDER
        bg = Color.PRIMARY_SOFT if self._selected else Color.SURFACE
        self.setStyleSheet(
            f"#PersonaItem {{ background: {bg}; border: 1px solid {border}; border-radius: 12px; }}"
        )

    def mousePressEvent(self, event) -> None:
        self._on_click(self.contract)
        super().mousePressEvent(event)


class PersonaWorkshopView(QWidget):
    def __init__(self, context: AppContext, nav: Navigator) -> None:
        super().__init__()
        self._ctx = context
        self._nav = nav
        self._current: PersonaContract | None = None
        self._items: list[_PersonaItem] = []
        self._build()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(36, 30, 36, 24)
        outer.setSpacing(16)

        header = QVBoxLayout()
        header.setSpacing(4)
        header.addWidget(page_title("人设工坊"))
        header.addWidget(lead("用结构化刻度塑造面试官的风格。数值会被翻译成明确的行为指令，而不是丢给模型一个数字。"))
        outer.addLayout(header)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_list())
        splitter.addWidget(self._build_editor())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([300, 900])
        outer.addWidget(splitter, 1)

    def _build_list(self) -> QWidget:
        panel = QWidget()
        panel.setFixedWidth(300)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(icon_button("plus", "新建人设", self._new, kind="Primary"))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        host = QWidget()
        self._list_box = QVBoxLayout(host)
        self._list_box.setContentsMargins(0, 0, 12, 0)
        self._list_box.setSpacing(8)
        self._list_box.addStretch(1)
        scroll.setWidget(host)
        layout.addWidget(scroll, 1)
        return panel

    def _build_editor(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(4, 0, 12, 0)
        layout.setSpacing(16)

        basic = Card()
        basic.add(h3("基本信息"))
        self._name = QLineEdit()
        self._name.setPlaceholderText("人设名称")
        self._archetype = QComboBox()
        for arch in PersonaArchetype:
            self._archetype.addItem(arch.label, arch)
        self._tier = QComboBox()
        for tier in CompanyTier:
            self._tier.addItem(tier.label, tier)
        self._job = QLineEdit()
        self._job.setPlaceholderText("职位头衔，如 后端技术二面官")
        self._flavor = QLineEdit()
        self._flavor.setPlaceholderText("公司气质，如 一家节奏很快的支付公司")
        self._voice = QComboBox()
        basic.add_layout(self._form_row("名称", self._name))
        basic.add_layout(self._form_row("性格原型", self._archetype))
        basic.add_layout(self._form_row("公司类型", self._tier))
        basic.add_layout(self._form_row("职位", self._job))
        basic.add_layout(self._form_row("公司气质", self._flavor))
        basic.add_layout(self._form_row("音色", self._voice))
        layout.addWidget(basic)

        speech = Card()
        speech.add(h3("表达风格"))
        self._s_code = _Slider("中英夹杂", 0, "0 纯中文，10 每句夹英文")
        self._s_verbose = _Slider("话唠程度", 4)
        self._s_warm = _Slider("态度温度", 5)
        self._s_formal = _Slider("正式度", 5)
        self._s_rate = _Slider("语速", 5)
        for s in (self._s_code, self._s_verbose, self._s_warm, self._s_formal, self._s_rate):
            speech.add(s)
        self._catchphrases = QLineEdit()
        self._catchphrases.setPlaceholderText("口头禅，用、分隔")
        self._banned = QLineEdit()
        self._banned.setPlaceholderText("禁止说出的话，用、分隔")
        speech.add_layout(self._form_row("口头禅", self._catchphrases))
        speech.add_layout(self._form_row("禁语", self._banned))
        layout.addWidget(speech)

        pressure = Card()
        pressure.add(h3("压迫感"))
        self._p_aggr = _Slider("攻击性", 4)
        self._p_intr = _Slider("打断倾向", 3)
        self._p_silence = _Slider("沉默施压", 2)
        self._p_challenge = _Slider("质疑频率", 4)
        self._p_vague = _Slider("含糊容忍", 5)
        for s in (self._p_aggr, self._p_intr, self._p_silence, self._p_challenge, self._p_vague):
            pressure.add(s)
        layout.addWidget(pressure)

        probing = Card()
        probing.add(h3("考察偏好"))
        self._pr_div = _Slider("发散度", 5)
        self._pr_depth = _Slider("追问深度", 5)
        self._pr_project = _Slider("项目经历", 7)
        self._pr_fund = _Slider("基础原理", 5)
        self._pr_design = _Slider("系统设计", 5)
        self._pr_coding = _Slider("编码实现", 4)
        self._pr_behav = _Slider("行为协作", 4)
        for s in (
            self._pr_div, self._pr_depth, self._pr_project, self._pr_fund,
            self._pr_design, self._pr_coding, self._pr_behav,
        ):
            probing.add(s)
        layout.addWidget(probing)

        rules = Card()
        rules.add(h3("开场与专属规则"))
        self._opening = QLineEdit()
        self._opening.setPlaceholderText("开场白，留空则用原型默认")
        self._rules = QPlainTextEdit()
        self._rules.setPlaceholderText("每行一条专属规则，会追加到面试官铁律中")
        self._rules.setFixedHeight(96)
        rules.add_layout(self._form_row("开场白", self._opening))
        rules.add(self._rules)
        layout.addWidget(rules)

        preview = Card(elevated=False)
        preview.add(h3("人格指令预览"))
        preview.add(faint("这是每轮重锚定时注入模型的身份与风格，改动即时反映。"))
        self._preview = QLabel("")
        self._preview.setWordWrap(True)
        self._preview.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._preview.setStyleSheet(
            f"color: {Color.TEXT_MUTED}; font-size: 12px; background: {Color.BG}; "
            f"border: 1px solid {Color.BORDER}; border-radius: 10px; padding: 12px;"
        )
        preview.add(self._preview)
        layout.addWidget(preview)

        layout.addWidget(Divider())
        self._btn_row = QHBoxLayout()
        self._save_btn = icon_button("save", "保存", self._save, kind="Primary")
        self._dup_btn = icon_button("copy", "复制为我的人设", self._duplicate)
        self._del_btn = icon_button("trash", "删除", self._delete, kind="Danger")
        self._btn_row.addWidget(self._save_btn)
        self._btn_row.addWidget(self._dup_btn)
        self._btn_row.addStretch(1)
        self._btn_row.addWidget(self._del_btn)
        layout.addLayout(self._btn_row)
        layout.addStretch(1)

        self._wire_preview()
        scroll.setWidget(host)
        return scroll

    def _form_row(self, caption: str, widget: QWidget):
        row = QHBoxLayout()
        row.setSpacing(10)
        label = QLabel(caption)
        label.setFixedWidth(72)
        label.setStyleSheet(f"color: {Color.TEXT_MUTED};")
        row.addWidget(label)
        row.addWidget(widget, 1)
        return row

    def _wire_preview(self) -> None:
        for slider in (
            self._s_code, self._s_verbose, self._s_warm, self._s_formal, self._s_rate,
            self._p_aggr, self._p_intr, self._p_silence, self._p_challenge, self._p_vague,
            self._pr_div, self._pr_depth, self._pr_project, self._pr_fund,
            self._pr_design, self._pr_coding, self._pr_behav,
        ):
            slider.on_change(self._refresh_preview)
        self._archetype.currentIndexChanged.connect(self._refresh_preview)
        self._tier.currentIndexChanged.connect(self._refresh_preview)
        for field in (self._name, self._job, self._flavor, self._catchphrases, self._banned, self._opening):
            field.textChanged.connect(self._refresh_preview)

    # ------------------------------------------------------------------

    def on_show(self) -> None:
        spawn(self._load_list(), context="加载人设")

    async def _load_list(self) -> None:
        personas = await self._ctx.personas.list_all()
        self._populate_voices()
        while self._list_box.count() > 1:
            item = self._list_box.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._items.clear()
        for contract in personas:
            item = _PersonaItem(contract, self._select)
            self._items.append(item)
            self._list_box.insertWidget(self._list_box.count() - 1, item)
        if personas and self._current is None:
            self._select(personas[0])

    def _populate_voices(self) -> None:
        if self._voice.count() > 0:
            return
        self._voice.addItem("跟随全局默认", "")
        catalog = self._ctx.config.settings.realtime.catalog()
        for voice in catalog.voices:
            self._voice.addItem(VOICE_LABELS.get(voice, voice), voice)

    def _select(self, contract: PersonaContract) -> None:
        self._current = contract
        self._load_form(contract)
        for item in self._items:
            item.set_selected(item.contract.id == contract.id and contract.id is not None)
        builtin = contract.is_builtin
        self._save_btn.setVisible(not builtin)
        self._del_btn.setVisible(not builtin)
        self._dup_btn.setVisible(builtin)

    def _new(self) -> None:
        draft = PersonaContract(name="新面试官")
        self._current = draft
        self._load_form(draft)
        for item in self._items:
            item.set_selected(False)
        self._save_btn.setVisible(True)
        self._del_btn.setVisible(False)
        self._dup_btn.setVisible(False)

    def _load_form(self, c: PersonaContract) -> None:
        self._name.setText(c.name)
        self._archetype.setCurrentIndex(max(0, self._archetype.findData(c.archetype)))
        self._tier.setCurrentIndex(max(0, self._tier.findData(c.company_tier)))
        self._job.setText(c.job_title)
        self._flavor.setText(c.company_flavor)
        self._voice.setCurrentIndex(max(0, self._voice.findData(c.voice)))
        self._s_code.set_value(c.speech.code_switch)
        self._s_verbose.set_value(c.speech.verbosity)
        self._s_warm.set_value(c.speech.warmth)
        self._s_formal.set_value(c.speech.formality)
        self._s_rate.set_value(c.speech.speech_rate)
        self._catchphrases.setText("、".join(c.speech.catchphrases))
        self._banned.setText("、".join(c.speech.banned_phrases))
        self._p_aggr.set_value(c.pressure.aggression)
        self._p_intr.set_value(c.pressure.interrupt_tendency)
        self._p_silence.set_value(c.pressure.silence_pressure)
        self._p_challenge.set_value(c.pressure.challenge_frequency)
        self._p_vague.set_value(c.pressure.tolerance_for_vagueness)
        self._pr_div.set_value(c.probing.divergence)
        self._pr_depth.set_value(c.probing.follow_up_depth)
        self._pr_project.set_value(c.probing.project_focus)
        self._pr_fund.set_value(c.probing.fundamentals_focus)
        self._pr_design.set_value(c.probing.system_design_focus)
        self._pr_coding.set_value(c.probing.coding_focus)
        self._pr_behav.set_value(c.probing.behavioral_focus)
        self._opening.setText(c.opening_line)
        self._rules.setPlainText("\n".join(c.extra_rules))
        self._refresh_preview()

    def _split(self, text: str) -> list[str]:
        return [p.strip() for p in text.replace(",", "、").split("、") if p.strip()]

    def _read_form(self) -> PersonaContract:
        return PersonaContract(
            id=self._current.id if self._current else None,
            name=self._name.text().strip() or "未命名面试官",
            archetype=combo_enum(self._archetype, PersonaArchetype, PersonaArchetype.STRUCTURED),
            company_tier=combo_enum(self._tier, CompanyTier, CompanyTier.BIG_TECH),
            job_title=self._job.text().strip() or "技术面试官",
            company_flavor=self._flavor.text().strip() or "一家节奏很快的公司",
            voice=self._voice.currentData() or "",
            speech=SpeechStyle(
                code_switch=self._s_code.value(),
                verbosity=self._s_verbose.value(),
                warmth=self._s_warm.value(),
                formality=self._s_formal.value(),
                speech_rate=self._s_rate.value(),
                catchphrases=self._split(self._catchphrases.text()),
                banned_phrases=self._split(self._banned.text()),
            ),
            pressure=PressureProfile(
                aggression=self._p_aggr.value(),
                interrupt_tendency=self._p_intr.value(),
                silence_pressure=self._p_silence.value(),
                challenge_frequency=self._p_challenge.value(),
                tolerance_for_vagueness=self._p_vague.value(),
            ),
            probing=ProbingProfile(
                divergence=self._pr_div.value(),
                follow_up_depth=self._pr_depth.value(),
                project_focus=self._pr_project.value(),
                fundamentals_focus=self._pr_fund.value(),
                system_design_focus=self._pr_design.value(),
                coding_focus=self._pr_coding.value(),
                behavioral_focus=self._pr_behav.value(),
            ),
            opening_line=self._opening.text().strip(),
            extra_rules=[r.strip() for r in self._rules.toPlainText().splitlines() if r.strip()],
        )

    def _refresh_preview(self) -> None:
        try:
            contract = self._read_form()
        except Exception:
            return
        text = contract.identity_block() + "\n\n" + contract.style_block()
        self._preview.setText(text)

    def _save(self) -> None:
        contract = self._read_form()
        spawn(self._do_save(contract), context="保存人设")

    async def _do_save(self, contract: PersonaContract) -> None:
        saved = await self._ctx.personas.save(contract)
        self._current = saved
        await self._load_list()
        self._select(saved)
        self._nav.toast("人设已保存", kind="success")

    def _duplicate(self) -> None:
        if self._current is None or self._current.id is None:
            return
        spawn(self._do_duplicate(self._current), context="复制人设")

    async def _do_duplicate(self, source: PersonaContract) -> None:
        name = await self._ctx.personas.unique_name(f"{source.name} 副本")
        clone = self._read_form().model_copy(update={"id": None, "name": name, "is_builtin": False})
        saved = await self._ctx.personas.save(clone)
        self._current = saved
        await self._load_list()
        self._select(saved)
        self._nav.toast(f"已复制为「{name}」，现在可以编辑了", kind="success")

    def _delete(self) -> None:
        if self._current is None or self._current.id is None:
            return
        spawn(self._do_delete(self._current.id), context="删除人设")

    async def _do_delete(self, persona_id: int) -> None:
        try:
            await self._ctx.personas.delete(persona_id)
        except ValueError as exc:
            self._nav.toast(str(exc), kind="error")
            return
        self._current = None
        await self._load_list()
        self._nav.toast("人设已删除", kind="info")
