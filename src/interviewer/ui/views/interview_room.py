from __future__ import annotations

import logging

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ...app.async_utils import spawn
from ...app.context import AppContext
from ...core.events import (
    AudioLevel,
    CopilotHint,
    DirectorDecided,
    DriftDetected,
    ElapsedTick,
    EngineFailure,
    InterruptionFired,
    PhaseChanged,
    RealtimeStateChanged,
    SpeechActivity,
    StarProgress,
    TranscriptCommitted,
    TranscriptDelta,
)
from ...core.types import InterviewPhase, Speaker, StarElement
from ...domain.interview import InterviewState
from .. import icons
from ..navigation import Navigator, Page
from ..theme import Color
from ..widgets.audio_meter import PulseOrb
from ..widgets.code_editor import LANGUAGES, CodeEditor
from ..widgets.common import Badge, Card, Panel, faint, h3, icon_button
from ..widgets.flow_layout import FlowLayout
from ..widgets.transcript_view import TranscriptView
from ..widgets.video_tile import CameraTile, SpeakerFrame

logger = logging.getLogger(__name__)


def _mmss(ms: int) -> str:
    total = max(0, ms) // 1000
    return f"{total // 60:02d}:{total % 60:02d}"


class _ControlButton(QPushButton):
    def __init__(
        self,
        text: str,
        glyph: str,
        *,
        danger: bool = False,
        primary: bool = False,
    ) -> None:
        super().__init__(text)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(44)
        self.setMinimumWidth(104)
        obj = "Danger" if danger else ("Primary" if primary else "Ghost")
        self.setObjectName(obj)
        tone = Color.TEXT_ON_PRIMARY if obj != "Ghost" else Color.TEXT_MUTED
        self._tone = tone
        self.set_glyph(glyph)

    def set_glyph(self, glyph: str) -> None:
        self.setIcon(icons.icon(glyph, size=17, color=self._tone))
        self.setIconSize(icons.icon_size(17))


class InterviewerStage(Panel):
    def __init__(self, name: str) -> None:
        super().__init__(
            object_name="Stage",
            qss=(
                f"#Stage {{ background: {Color.STAGE_BG}; "
                f"border: 1px solid {Color.STAGE_BORDER}; border-radius: 14px; }}"
            ),
        )
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(12)
        self.orb = PulseOrb(size=150)
        layout.addWidget(self.orb, 0, Qt.AlignmentFlag.AlignCenter)
        self.name = QLabel(name)
        self.name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.name.setStyleSheet(f"color: {Color.STAGE_TEXT}; font-size: 17px; font-weight: 700;")
        layout.addWidget(self.name)
        self.caption = QLabel("正在接通…")
        self.caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.caption.setStyleSheet(f"color: {Color.STAGE_TEXT_MUTED}; font-size: 13px;")
        layout.addWidget(self.caption)


class StarStrip(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self._pills: dict[StarElement, QLabel] = {}
        for element in StarElement:
            pill = QLabel(element.label.split(" ")[0])
            pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
            pill.setFixedHeight(30)
            self._pills[element] = pill
            layout.addWidget(pill, 1)
        self.update_state(set())

    def update_state(self, present: set[StarElement]) -> None:
        for element, pill in self._pills.items():
            got = element in present
            color = Color.SUCCESS if got else Color.TEXT_FAINT
            bg = Color.PRIMARY_SOFT if got else Color.SURFACE_SUBTLE
            pill.setStyleSheet(
                f"background: {bg}; color: {color}; border-radius: 8px; "
                f"font-size: 12px; font-weight: 600;"
            )


class InterviewRoomView(QWidget):
    def __init__(self, context: AppContext, nav: Navigator) -> None:
        super().__init__()
        self._ctx = context
        self._nav = nav
        self._state: InterviewState | None = None
        self._unsubs: list = []
        self._phase_label = "开场破冰"
        self._confirm_end = False
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 16, 24, 16)
        root.setSpacing(14)
        root.addWidget(self._build_topbar())

        body = QHBoxLayout()
        body.setSpacing(16)
        body.addWidget(self._build_stage_column(), 1)
        body.addWidget(self._build_side_panel())
        root.addLayout(body, 1)
        root.addWidget(self._build_controls())

    # ---------- 顶栏 ----------

    def _build_topbar(self) -> QWidget:
        bar = Card(padding=14, elevated=False)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        self._phase_badge = Badge("开场破冰", color=Color.PRIMARY)
        row.addWidget(self._phase_badge)
        self._conn = QLabel("● 接通中")
        self._conn.setStyleSheet(f"color: {Color.WARNING}; font-size: 12px;")
        row.addWidget(self._conn)
        row.addStretch(1)
        self._elapsed = QLabel("00:00")
        self._elapsed.setStyleSheet(f"color: {Color.TEXT}; font-size: 20px; font-weight: 700;")
        row.addWidget(self._elapsed)
        self._remaining = QLabel("剩余 --:--")
        self._remaining.setStyleSheet(f"color: {Color.TEXT_FAINT}; font-size: 13px;")
        row.addWidget(self._remaining)
        bar.add_layout(row)
        return bar

    # ---------- 舞台列 ----------

    def _build_stage_column(self) -> QWidget:
        col = QWidget()
        layout = QVBoxLayout(col)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        videos = QHBoxLayout()
        videos.setSpacing(14)
        self._stage = InterviewerStage("面试官")
        self._stage_frame = SpeakerFrame(self._stage, accent=Color.INTERVIEWER)
        videos.addWidget(self._stage_frame, 1)

        self._camera = CameraTile(name="我")
        self._camera.setMinimumSize(300, 200)
        self._camera_frame = SpeakerFrame(self._camera, accent=Color.CANDIDATE)
        videos.addWidget(self._camera_frame, 1)
        layout.addLayout(videos)

        self._splitter = QSplitter(Qt.Orientation.Vertical)
        transcript_card = Card(padding=12)
        transcript_card.add(h3("实时字幕"))
        self._transcript = TranscriptView()
        transcript_card.add(self._transcript)
        self._splitter.addWidget(transcript_card)

        self._code_panel = self._build_code_panel()
        self._code_panel.setVisible(False)
        self._splitter.addWidget(self._code_panel)
        self._splitter.setSizes([500, 0])
        layout.addWidget(self._splitter, 1)
        return col

    def _build_code_panel(self) -> QWidget:
        card = Card(padding=12)
        head = QHBoxLayout()
        head.addWidget(h3("代码沙盒"), 1)
        self._lang = QComboBox()
        self._lang.addItems(list(LANGUAGES))
        self._lang.currentTextChanged.connect(lambda lang: self._editor.set_language(lang))
        head.addWidget(self._lang)
        self._submit_btn = icon_button("send", "提交给面试官", self._submit_code)
        head.addWidget(self._submit_btn)
        card.add_layout(head)
        self._editor = CodeEditor("python")
        self._editor.setMinimumHeight(200)
        card.add(self._editor)
        return card

    # ---------- 侧栏 ----------

    def _build_side_panel(self) -> QWidget:
        panel = QWidget()
        panel.setFixedWidth(330)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        self._copilot_card = Card()
        head = QHBoxLayout()
        head.addWidget(h3("提词器"), 1)
        self._copilot_hint = faint("卡壳时点下方「求助提词」，我会给关键词。")
        self._copilot_card.add_layout(head)
        self._copilot_card.add(self._copilot_hint)
        kw_host = QWidget()
        self._kw_flow = FlowLayout(kw_host, spacing=8)
        self._copilot_card.add(kw_host)
        self._copilot_outline = QVBoxLayout()
        self._copilot_outline.setSpacing(4)
        self._copilot_card.add_layout(self._copilot_outline)
        layout.addWidget(self._copilot_card)

        self._star_card = Card()
        self._star_card.add(h3("STAR 完整度"))
        self._star_card.add(faint("回答行为题时，逐项点亮情境/任务/行动/结果。"))
        self._star_strip = StarStrip()
        self._star_card.add(self._star_strip)
        self._star_card.setVisible(False)
        layout.addWidget(self._star_card)

        layout.addStretch(1)
        return panel

    # ---------- 控制栏 ----------

    def _build_controls(self) -> QWidget:
        bar = Card(padding=12, elevated=False)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)

        self._mute_btn = _ControlButton("静音", "mic")
        self._mute_btn.setCheckable(True)
        self._mute_btn.clicked.connect(self._toggle_mute)
        self._cam_btn = _ControlButton("关闭摄像头", "video")
        self._cam_btn.setCheckable(True)
        self._cam_btn.clicked.connect(self._toggle_camera)
        self._hint_btn = _ControlButton("求助提词", "bulb", primary=True)
        self._hint_btn.clicked.connect(self._request_hint)
        self._code_btn = _ControlButton("代码沙盒", "code")
        self._code_btn.setCheckable(True)
        self._code_btn.clicked.connect(self._toggle_code)
        self._interrupt_btn = _ControlButton("打断面试官", "zap")
        self._interrupt_btn.clicked.connect(self._interrupt)

        row.addWidget(self._mute_btn)
        row.addWidget(self._cam_btn)
        row.addWidget(self._code_btn)
        row.addStretch(1)
        row.addWidget(self._hint_btn)
        row.addWidget(self._interrupt_btn)
        self._end_btn = _ControlButton("结束面试", "exit", danger=True)
        self._end_btn.clicked.connect(self._end)
        row.addWidget(self._end_btn)
        bar.add_layout(row)
        return bar

    # ==================================================================
    # 生命周期
    # ==================================================================

    def begin(self, state: InterviewState) -> None:
        self._state = state
        self._reset_ui(state)
        features = self._ctx.config.settings.features
        self._mute_btn.setChecked(False)
        self._mute_btn.setText("静音")
        self._mute_btn.set_glyph("mic")
        if features.camera_enabled:
            started = self._camera.start()
            self._cam_btn.setChecked(not started)
            self._apply_camera_button(started)
        else:
            self._cam_btn.setChecked(True)
            self._apply_camera_button(False)
        self._hint_btn.setEnabled(features.copilot_enabled)
        self._subscribe()
        spawn(self._run(state), context="面试")

    def _reset_ui(self, state: InterviewState) -> None:
        self._confirm_end = False
        self._end_btn.setText("结束面试")
        self._transcript.clear()
        self._stage.name.setText(state.persona.name)
        self._stage.caption.setText("正在接通…")
        self._conn.setText("● 接通中")
        self._conn.setStyleSheet(f"color: {Color.WARNING}; font-size: 12px;")
        self._elapsed.setText("00:00")
        self._remaining.setText(f"剩余 {_mmss(state.plan.total_ms)}")
        self._phase_label = InterviewPhase.WARMUP.label
        self._phase_badge.apply(self._phase_label, color=Color.PRIMARY)
        self._star_card.setVisible(False)
        self._code_btn.setChecked(False)
        self._code_panel.setVisible(False)
        self._clear_copilot()

    async def _run(self, state: InterviewState) -> None:
        try:
            await self._ctx.engine.start(state)
        except Exception as exc:
            self._teardown()
            self._nav.toast(getattr(exc, "user_message", str(exc)), kind="error")
            self._nav.navigate(Page.PREPARE)
            return
        await self._ctx.engine.wait_finished()
        session_id = state.session_id
        reviewable = state.reviewable
        self._teardown()
        if reviewable:
            self._nav.open_review(session_id, generate=True)
        else:
            self._nav.toast("面试不足 5 分钟，未生成完整复盘", kind="warning")
            self._nav.navigate(Page.DASHBOARD)

    def _subscribe(self) -> None:
        bus = self._ctx.bus
        self._unsubs = [
            bus.subscribe(RealtimeStateChanged, self._on_conn),
            bus.subscribe(SpeechActivity, self._on_speech),
            bus.subscribe(AudioLevel, self._on_level),
            bus.subscribe(TranscriptDelta, self._on_delta),
            bus.subscribe(TranscriptCommitted, self._on_commit),
            bus.subscribe(PhaseChanged, self._on_phase),
            bus.subscribe(DirectorDecided, self._on_director),
            bus.subscribe(StarProgress, self._on_star),
            bus.subscribe(CopilotHint, self._on_hint),
            bus.subscribe(InterruptionFired, self._on_interrupt),
            bus.subscribe(ElapsedTick, self._on_tick),
            bus.subscribe(DriftDetected, self._on_drift),
            bus.subscribe(EngineFailure, self._on_failure),
        ]

    def _teardown(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs = []
        self._camera.stop()
        self._state = None

    # ==================================================================
    # 事件处理
    # ==================================================================

    def _on_conn(self, event: RealtimeStateChanged) -> None:
        if event.connected:
            self._conn.setText("● 已接通")
            self._conn.setStyleSheet(f"color: {Color.SUCCESS}; font-size: 12px;")
            self._stage.caption.setText("面试开始")
        else:
            self._conn.setText("● 连接断开")
            self._conn.setStyleSheet(f"color: {Color.DANGER}; font-size: 12px;")

    def _on_speech(self, event: SpeechActivity) -> None:
        self._camera_frame.set_active(event.speaking)

    def _on_level(self, event: AudioLevel) -> None:
        self._camera.set_level(event.candidate)
        self._stage.orb.set_level(event.interviewer)
        speaking = event.interviewer > 0.02
        self._stage.orb.set_active(speaking)
        self._stage_frame.set_active(speaking)

    def _on_delta(self, event: TranscriptDelta) -> None:
        speaker = Speaker(event.speaker)
        self._transcript.set_partial(speaker, event.text)

    def _on_commit(self, event: TranscriptCommitted) -> None:
        speaker = Speaker(event.speaker)
        self._transcript.commit(speaker, event.text)

    def _on_phase(self, event: PhaseChanged) -> None:
        self._phase_label = event.phase.label
        color = Color.WARNING if event.phase is InterviewPhase.STRESS else Color.PRIMARY
        if event.phase is InterviewPhase.CLOSING:
            color = Color.ACCENT
        self._phase_badge.apply(self._phase_label, color=color)
        self._stage.caption.setText(f"{self._phase_label} · {event.reason}")
        if event.phase is InterviewPhase.CODING and not self._code_btn.isChecked():
            self._code_btn.setChecked(True)
            self._toggle_code()

    def _on_director(self, event: DirectorDecided) -> None:
        skill = f" · {event.target_skill}" if event.target_skill else ""
        self._stage.caption.setText(f"{self._phase_label} · {event.intent.label}{skill}")

    def _on_star(self, event: StarProgress) -> None:
        self._star_card.setVisible(event.is_behavioral)
        if event.is_behavioral:
            self._star_strip.update_state(set(event.present))

    def _on_hint(self, event: CopilotHint) -> None:
        self._clear_copilot()
        self._copilot_hint.setText(event.caution or "给你几个可以展开的方向：")
        for kw in event.keywords[:8]:
            self._kw_flow.addWidget(Badge(kw, color=Color.ACCENT))
        for line in event.outline[:5]:
            item = QLabel("· " + line)
            item.setWordWrap(True)
            item.setStyleSheet(f"color: {Color.TEXT_MUTED}; font-size: 13px;")
            self._copilot_outline.addWidget(item)

    def _on_interrupt(self, event: InterruptionFired) -> None:
        self._nav.toast(event.reason, kind="warning" if event.by_interviewer else "info")

    def _on_tick(self, event: ElapsedTick) -> None:
        self._elapsed.setText(_mmss(event.elapsed_ms))
        self._remaining.setText(f"剩余 {_mmss(event.remaining_ms)}")
        if event.remaining_ms <= 60_000:
            self._remaining.setStyleSheet(f"color: {Color.DANGER}; font-size: 13px; font-weight: 700;")
        elif event.remaining_ms <= 180_000:
            self._remaining.setStyleSheet(f"color: {Color.WARNING}; font-size: 13px;")

    def _on_drift(self, event: DriftDetected) -> None:
        logger.info("人格漂移已修复=%s kind=%s", event.repaired, event.kind.value)

    def _on_failure(self, event: EngineFailure) -> None:
        if not event.fatal:
            self._nav.toast(event.user_message, kind="error")

    # ==================================================================
    # 交互
    # ==================================================================

    def _toggle_mute(self) -> None:
        muted = self._mute_btn.isChecked()
        self._ctx.engine.set_muted(muted)
        self._mute_btn.setText("已静音" if muted else "静音")
        self._mute_btn.set_glyph("mic_off" if muted else "mic")

    def _toggle_camera(self) -> None:
        off = self._cam_btn.isChecked()
        if off:
            self._camera.stop()
            self._apply_camera_button(False)
        else:
            started = self._camera.start()
            self._cam_btn.setChecked(not started)
            self._apply_camera_button(started)
            if not started:
                self._nav.toast("没有检测到摄像头", kind="warning")

    def _apply_camera_button(self, on: bool) -> None:
        self._cam_btn.setText("关闭摄像头" if on else "开启摄像头")
        self._cam_btn.set_glyph("video" if on else "video_off")

    def _toggle_code(self) -> None:
        show = self._code_btn.isChecked()
        self._code_panel.setVisible(show)
        if show:
            self._splitter.setSizes([320, 320])
        else:
            self._splitter.setSizes([600, 0])

    def _request_hint(self) -> None:
        self._hint_btn.setEnabled(False)
        QTimer.singleShot(3000, lambda: self._hint_btn.setEnabled(True))
        spawn(self._ctx.engine.request_hint(), context="求助提词")

    def _submit_code(self) -> None:
        source = self._editor.source().strip()
        if not source:
            self._nav.toast("先写点代码再提交", kind="warning")
            return
        language = self._lang.currentText()
        self._nav.toast("已提交，面试官正在看你的代码", kind="info")
        spawn(self._ctx.engine.submit_code(language, source), context="提交代码")

    def _interrupt(self) -> None:
        spawn(self._ctx.engine.interrupt_interviewer(), context="打断面试官")

    def _end(self) -> None:
        if not self._confirm_end:
            self._confirm_end = True
            self._end_btn.setText("再次点击确认")
            QTimer.singleShot(3000, self._reset_end_button)
            return
        self._reset_end_button()
        self._end_btn.setEnabled(False)
        self._end_btn.setText("正在收尾…")
        spawn(self._ctx.engine.finish_early(), context="结束面试")

    def _reset_end_button(self) -> None:
        self._confirm_end = False
        if self._end_btn.text() == "再次点击确认":
            self._end_btn.setText("结束面试")

    def _clear_copilot(self) -> None:
        self._kw_flow.clear()
        while self._copilot_outline.count():
            item = self._copilot_outline.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
