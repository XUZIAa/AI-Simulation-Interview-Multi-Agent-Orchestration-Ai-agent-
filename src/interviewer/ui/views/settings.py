from __future__ import annotations

import logging
import webbrowser
from collections.abc import Awaitable, Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...app.async_utils import spawn
from ...app.context import AppContext
from ...core.errors import ConfigError
from ...core.providers_catalog import (
    CHAT_PROVIDERS,
    REALTIME_PROVIDERS,
    ROLE_LABELS,
    VOICE_LABELS,
    ChatProvider,
    RoleBinding,
    model_traits,
)
from ...llm import ProbeResult, probe_chat
from ...realtime.audio_io import AudioDeviceInfo, input_devices, output_devices
from ...realtime.probe import probe_realtime
from ..navigation import Navigator
from ..theme import Color
from ..widgets.common import (
    AutoLabel,
    Card,
    TextButton,
    faint,
    h3,
    icon_button,
    page_title,
)

logger = logging.getLogger(__name__)


class _SliderRow(QWidget):
    def __init__(self, *, minimum: int, maximum: int, value: int, scale: float, suffix: str, decimals: int = 0) -> None:
        super().__init__()
        self._scale = scale
        self._suffix = suffix
        self._decimals = decimals
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setRange(minimum, maximum)
        self._slider.setValue(value)
        self._readout = QLabel("")
        self._readout.setFixedWidth(72)
        self._readout.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._readout.setStyleSheet(f"color: {Color.TEXT}; font-weight: 600;")
        self._slider.valueChanged.connect(self._render)
        layout.addWidget(self._slider, 1)
        layout.addWidget(self._readout)
        self._render()

    def _render(self) -> None:
        self._readout.setText(f"{self.value():.{self._decimals}f}{self._suffix}")

    def value(self) -> float:
        return self._slider.value() * self._scale


class _RoleEditor(QWidget):
    def __init__(self) -> None:
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)
        row = QHBoxLayout()
        row.setSpacing(10)
        self.provider = QComboBox()
        for key, provider in CHAT_PROVIDERS.items():
            self.provider.addItem(provider.label, key)
        self.model = QComboBox()
        self.model.setEditable(True)
        self.provider.currentIndexChanged.connect(self._reload_models)
        self.model.currentTextChanged.connect(self._check_traits)
        row.addWidget(self.provider, 3)
        row.addWidget(self.model, 4)
        root.addLayout(row)
        self._warn = AutoLabel(color=Color.WARNING, size=12)
        root.addWidget(self._warn)

    def _check_traits(self) -> None:
        if model_traits(self.model.currentText()).reasoning:
            self._warn.setText(
                "推理模型的思维链会占满输出配额，本项目全靠结构化输出，建议换成非推理模型"
            )
        else:
            self._warn.setText("")

    def _reload_models(self) -> None:
        key = self.provider.currentData()
        self.model.clear()
        self.model.addItems(list(CHAT_PROVIDERS[key].models))

    def set_binding(self, binding: RoleBinding) -> None:
        idx = self.provider.findData(binding.provider)
        self.provider.setCurrentIndex(max(0, idx))
        self._reload_models()
        self.model.setCurrentText(binding.model or CHAT_PROVIDERS[binding.provider].default_model)

    def binding(self) -> RoleBinding:
        return RoleBinding(provider=self.provider.currentData(), model=self.model.currentText().strip())


class _ProbeRow(QWidget):
    """带连通性测试的行基类：一行控件 + 一行结果，结果为空时自动隐藏。"""

    def __init__(self) -> None:
        super().__init__()
        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(0, 0, 0, 0)
        self._root.setSpacing(5)
        self.row = QHBoxLayout()
        self.row.setSpacing(10)
        self._root.addLayout(self.row)
        self._result = AutoLabel()
        self._root.addWidget(self._result)

    def report(self, ok: bool | None, text: str) -> None:
        color = Color.TEXT_MUTED if ok is None else (Color.SUCCESS if ok else Color.DANGER)
        self._result.setStyleSheet(f"color: {color}; font-size: 12px;")
        self._result.setText(text)

    def run_probe(
        self,
        button: QPushButton,
        factory: Callable[[], Awaitable[ProbeResult]],
        pending: str,
    ) -> None:
        button.setEnabled(False)
        self.report(None, pending)

        def done(result: ProbeResult) -> None:
            button.setEnabled(True)
            self.report(result.ok, result.detail)

        def failed(exc: Exception) -> None:
            button.setEnabled(True)
            self.report(False, f"{exc.__class__.__name__}: {str(exc)[:120]}")

        spawn(factory(), on_success=done, on_error=failed, context="连通性测试")


class _ApiKeyRow(_ProbeRow):
    def __init__(self, provider_key: str, provider: ChatProvider) -> None:
        super().__init__()
        self.provider_key = provider_key
        self._provider = provider

        name = QLabel(provider.label)
        name.setFixedWidth(150)
        name.setStyleSheet(f"color: {Color.TEXT}; font-weight: 600;")
        self.field = QLineEdit()
        self.field.setEchoMode(QLineEdit.EchoMode.Password)
        self.field.setPlaceholderText("粘贴 API Key")
        reveal = QCheckBox("显示")
        reveal.toggled.connect(
            lambda on: self.field.setEchoMode(
                QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password
            )
        )
        self._test_btn = icon_button("check_circle", "测试", self._test)
        self._test_btn.setFixedWidth(96)

        self.row.addWidget(name)
        self.row.addWidget(self.field, 1)
        self.row.addWidget(reveal)
        self.row.addWidget(self._test_btn)
        if provider.console_url:
            self.row.addWidget(TextButton("获取", lambda: webbrowser.open(provider.console_url)))

    def _test(self) -> None:
        key = self.field.text().strip()
        if not key:
            self.report(False, "先粘贴 API Key 再测试")
            return
        model = self._provider.default_model
        self.run_probe(
            self._test_btn,
            lambda: probe_chat(
                provider_key=self.provider_key,
                base_url=self._provider.base_url,
                api_key=key,
                model=model,
            ),
            f"正在用 {model} 测试…",
        )


class SettingsView(QWidget):
    def __init__(self, context: AppContext, nav: Navigator) -> None:
        super().__init__()
        self._ctx = context
        self._nav = nav
        self._key_rows: dict[str, _ApiKeyRow] = {}
        self._role_editors: dict[str, _RoleEditor] = {}
        self._inputs: list[AudioDeviceInfo] = []
        self._outputs: list[AudioDeviceInfo] = []
        self._build()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(36, 30, 36, 20)
        outer.setSpacing(18)

        header = QHBoxLayout()
        col = QVBoxLayout()
        col.setSpacing(4)
        col.addWidget(page_title("设置"))
        header.addLayout(col, 1)
        self._save_btn = icon_button("save", "保存设置", self._save, kind="Primary")
        self._save_btn.setFixedWidth(150)
        header.addWidget(self._save_btn, 0, Qt.AlignmentFlag.AlignTop)
        outer.addLayout(header)

        tabs = QTabWidget()
        tabs.addTab(self._models_tab(), "模型与密钥")
        tabs.addTab(self._audio_tab(), "音频")
        tabs.addTab(self._features_tab(), "功能")
        outer.addWidget(tabs, 1)

    def _scroll(self, inner: QWidget) -> QScrollArea:
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setWidget(inner)
        return area

    def _models_tab(self) -> QWidget:
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(2, 16, 12, 16)
        layout.setSpacing(16)

        keys_card = Card()
        keys_card.add(h3("API 密钥"))
        for key, provider in CHAT_PROVIDERS.items():
            row = _ApiKeyRow(key, provider)
            self._key_rows[key] = row
            keys_card.add(row)
        layout.addWidget(keys_card)

        roles_card = Card()
        roles_card.add(h3("角色模型绑定"))
        grid = QGridLayout()
        grid.setSpacing(12)
        grid.setColumnStretch(1, 1)
        for r, (role_key, role_label) in enumerate(ROLE_LABELS.items()):
            caption = QLabel(role_label)
            caption.setWordWrap(True)
            caption.setStyleSheet(f"color: {Color.TEXT_MUTED};")
            editor = _RoleEditor()
            self._role_editors[role_key] = editor
            grid.addWidget(caption, r, 0)
            grid.addWidget(editor, r, 1)
        roles_card.add_layout(grid)
        layout.addWidget(roles_card)

        rt_card = Card()
        rt_card.add(h3("实时语音"))
        rt_grid = QGridLayout()
        rt_grid.setSpacing(12)
        rt_grid.setColumnStretch(1, 1)
        self._rt_provider = QComboBox()
        for key, provider in REALTIME_PROVIDERS.items():
            self._rt_provider.addItem(provider.label, key)
        self._rt_model = QComboBox()
        self._rt_model.setEditable(True)
        self._rt_voice = QComboBox()
        self._rt_provider.currentIndexChanged.connect(self._reload_realtime)
        self._rt_temp = _SliderRow(minimum=10, maximum=150, value=85, scale=0.01, suffix="", decimals=2)
        rt_fields = (
            ("供应商", self._rt_provider),
            ("模型", self._rt_model),
            ("音色", self._rt_voice),
            ("语气温度", self._rt_temp),
        )
        for r, (cap, widget) in enumerate(rt_fields):
            label = QLabel(cap)
            label.setStyleSheet(f"color: {Color.TEXT_MUTED};")
            rt_grid.addWidget(label, r, 0)
            rt_grid.addWidget(widget, r, 1)
        rt_card.add_layout(rt_grid)

        self._rt_probe = _ProbeRow()
        self._rt_test_btn = icon_button("check_circle", "测试实时语音连通", self._test_realtime)
        self._rt_probe.row.addWidget(self._rt_test_btn)
        self._rt_probe.row.addStretch(1)
        rt_card.add(self._rt_probe)

        layout.addWidget(rt_card)
        layout.addStretch(1)
        return self._scroll(host)

    def _test_realtime(self) -> None:
        provider = REALTIME_PROVIDERS[self._rt_provider.currentData()]
        model = self._rt_model.currentText().strip()
        # 实时语音与文本模型共用同一份密钥，直接取上面那一行的输入
        row = self._key_rows.get(provider.credential_key)
        api_key = row.field.text().strip() if row is not None else ""
        if not api_key:
            owner = CHAT_PROVIDERS.get(provider.credential_key)
            name = owner.label if owner else provider.credential_key
            self._rt_probe.report(False, f"先在上面填写「{name}」的 API Key")
            return
        self._rt_probe.run_probe(
            self._rt_test_btn,
            lambda: probe_realtime(provider=provider, api_key=api_key, model=model),
            f"正在握手 {model} …",
        )

    def _audio_tab(self) -> QWidget:
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(2, 16, 12, 16)
        layout.setSpacing(16)

        card = Card()
        card.add(h3("音频设备"))
        card.add(faint("建议佩戴耳机，避免扬声器外放导致面试官听到自己的声音而误打断。"))
        grid = QGridLayout()
        grid.setSpacing(12)
        grid.setColumnStretch(1, 1)
        self._input_combo = QComboBox()
        self._output_combo = QComboBox()
        self._gain = _SliderRow(minimum=20, maximum=400, value=100, scale=0.01, suffix="x", decimals=2)
        self._vad = _SliderRow(minimum=5, maximum=95, value=42, scale=0.01, suffix="", decimals=2)
        self._silence = _SliderRow(minimum=200, maximum=2000, value=620, scale=1.0, suffix="ms", decimals=0)
        self._semantic = QCheckBox("启用语义打断（区分附和与真正插话，推荐开启）")
        self._echo_guard = QCheckBox("抑制扬声器回流（外放时必须开启，否则面试官会被自己的声音打断）")
        rows = (
            ("麦克风", self._input_combo),
            ("扬声器", self._output_combo),
            ("麦克风增益", self._gain),
            ("人声灵敏度", self._vad),
            ("停顿判定", self._silence),
        )
        for r, (cap, widget) in enumerate(rows):
            label = QLabel(cap)
            label.setStyleSheet(f"color: {Color.TEXT_MUTED};")
            grid.addWidget(label, r, 0)
            grid.addWidget(widget, r, 1)
        card.add_layout(grid)
        card.add(self._semantic)
        card.add(self._echo_guard)
        layout.addWidget(card)
        layout.addStretch(1)
        return self._scroll(host)

    def _features_tab(self) -> QWidget:
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(2, 16, 12, 16)
        layout.setSpacing(16)

        card = Card()
        card.add(h3("功能开关"))
        self._camera = QCheckBox("面试间开启摄像头自视图（视频仅本地渲染，不上传）")
        self._copilot = QCheckBox("允许实时提词器（卡壳时给关键词提示）")
        self._coding = QCheckBox("默认开启代码沙盒环节")
        self._save_audio = QCheckBox("保存面试录音（用于复盘的副语言分析）")
        for box in (self._camera, self._copilot, self._coding, self._save_audio):
            card.add(box)
        layout.addWidget(card)
        layout.addStretch(1)
        return self._scroll(host)

    # ------------------------------------------------------------------

    def _reload_realtime(self) -> None:
        key = self._rt_provider.currentData()
        provider = REALTIME_PROVIDERS[key]
        self._rt_model.clear()
        self._rt_model.addItems(list(provider.models))
        self._rt_voice.clear()
        for voice in provider.voices:
            self._rt_voice.addItem(VOICE_LABELS.get(voice, voice), voice)

    def on_show(self) -> None:
        self._load_devices()
        self._load_values()

    def _load_devices(self) -> None:
        try:
            self._inputs = input_devices()
            self._outputs = output_devices()
        except Exception:
            logger.warning("音频设备枚举失败", exc_info=True)
            self._inputs, self._outputs = [], []
        self._input_combo.clear()
        self._input_combo.addItem("系统默认", "")
        for dev in self._inputs:
            self._input_combo.addItem(dev.name, dev.name)
        self._output_combo.clear()
        self._output_combo.addItem("系统默认", "")
        for dev in self._outputs:
            self._output_combo.addItem(dev.name, dev.name)

    def _load_values(self) -> None:
        s = self._ctx.config.settings
        for key, row in self._key_rows.items():
            try:
                row.field.setText(self._ctx.config.get_api_key(key))
            except ConfigError:
                row.field.setText("")
        for role_key, editor in self._role_editors.items():
            editor.set_binding(s.roles.get(role_key) or RoleBinding(provider="deepseek"))

        idx = self._rt_provider.findData(s.realtime.provider)
        self._rt_provider.setCurrentIndex(max(0, idx))
        self._reload_realtime()
        if s.realtime.model:
            self._rt_model.setCurrentText(s.realtime.model)
        vidx = self._rt_voice.findData(s.realtime.resolved_voice())
        self._rt_voice.setCurrentIndex(max(0, vidx))

        self._select_combo(self._input_combo, s.audio.input_device)
        self._select_combo(self._output_combo, s.audio.output_device)
        self._semantic.setChecked(s.audio.semantic_vad)
        self._echo_guard.setChecked(s.audio.echo_guard)
        self._camera.setChecked(s.features.camera_enabled)
        self._copilot.setChecked(s.features.copilot_enabled)
        self._coding.setChecked(s.features.coding_round_enabled)
        self._save_audio.setChecked(s.features.save_audio)

    @staticmethod
    def _select_combo(combo: QComboBox, value: str) -> None:
        idx = combo.findData(value)
        combo.setCurrentIndex(max(0, idx))

    def _save(self) -> None:
        s = self._ctx.config.settings
        roles = {key: editor.binding() for key, editor in self._role_editors.items()}
        updated = s.model_copy(
            update={
                "roles": roles,
                "realtime": s.realtime.model_copy(
                    update={
                        "provider": self._rt_provider.currentData(),
                        "model": self._rt_model.currentText().strip(),
                        "voice": self._rt_voice.currentData() or "",
                        "temperature": round(self._rt_temp.value(), 2),
                    }
                ),
                "audio": s.audio.model_copy(
                    update={
                        "input_device": self._input_combo.currentData() or "",
                        "output_device": self._output_combo.currentData() or "",
                        "input_gain": round(self._gain.value(), 2),
                        "vad_threshold": round(self._vad.value(), 2),
                        "silence_duration_ms": int(self._silence.value()),
                        "semantic_vad": self._semantic.isChecked(),
                "echo_guard": self._echo_guard.isChecked(),
                    }
                ),
                "features": s.features.model_copy(
                    update={
                        "camera_enabled": self._camera.isChecked(),
                        "copilot_enabled": self._copilot.isChecked(),
                        "coding_round_enabled": self._coding.isChecked(),
                        "save_audio": self._save_audio.isChecked(),
                    }
                ),
            }
        )
        try:
            for key, row in self._key_rows.items():
                self._ctx.config.set_api_key(key, row.field.text().strip())
            self._ctx.config.save(updated)
        except ConfigError as exc:
            self._nav.toast(exc.user_message, kind="error")
            return
        spawn(self._ctx.reload_models(), context="刷新模型配置")
        self._nav.toast("设置已保存", kind="success")
