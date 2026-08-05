from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtMultimedia import QCamera, QMediaCaptureSession, QMediaDevices
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import QHBoxLayout, QLabel, QStackedLayout, QVBoxLayout, QWidget

from ..theme import Color
from .audio_meter import VoiceBars
from .common import Panel

logger = logging.getLogger(__name__)


class CameraTile(Panel):
    """摄像头自视图。视频只在本地渲染，不上传，随时可关。"""

    def __init__(self, *, name: str = "我") -> None:
        super().__init__(
            object_name="CamTile",
            qss=(
                f"#CamTile {{ background: {Color.STAGE_BG}; "
                f"border: 1px solid {Color.STAGE_BORDER}; border-radius: 14px; }}"
            ),
        )
        self._name = name
        self._camera: QCamera | None = None
        self._session: QMediaCaptureSession | None = None

        self._stack = QStackedLayout(self)
        self._stack.setContentsMargins(0, 0, 0, 0)
        self._stack.setStackingMode(QStackedLayout.StackingMode.StackAll)

        self._video = QVideoWidget()
        self._video.setStyleSheet("background: transparent; border-radius: 14px;")
        self._placeholder = self._build_placeholder()

        self._stack.addWidget(self._placeholder)
        self._stack.addWidget(self._video)

        self._badge = QLabel(name, self)
        self._badge.setStyleSheet(
            f"background: rgba(0, 0, 0, 0.55); color: {Color.STAGE_TEXT}; border-radius: 8px; "
            f"padding: 3px 10px; font-size: 12px; font-weight: 600;"
        )
        # 音量条做成瓦片内的叠加层，两侧瓦片才能等高
        self._bars = VoiceBars(color=Color.CANDIDATE, parent=self)
        self._bars.setFixedSize(72, 22)

    def set_level(self, level: float) -> None:
        self._bars.set_level(level)

    def _build_placeholder(self) -> QWidget:
        holder = QWidget()
        layout = QVBoxLayout(holder)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon = QLabel("◍")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet(f"color: {Color.STAGE_TEXT_MUTED}; font-size: 46px;")
        text = QLabel("摄像头已关闭")
        text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        text.setStyleSheet(f"color: {Color.STAGE_TEXT_MUTED}; font-size: 13px;")
        layout.addWidget(icon)
        layout.addWidget(text)
        return holder

    def start(self) -> bool:
        if self._camera is not None:
            return True
        device = QMediaDevices.defaultVideoInput()
        if device is None or device.isNull():
            logger.info("未检测到摄像头，保持占位画面")
            return False
        self._session = QMediaCaptureSession()
        self._camera = QCamera(device)
        self._session.setCamera(self._camera)
        self._session.setVideoOutput(self._video)
        self._camera.start()
        self._stack.setCurrentWidget(self._video)
        return True

    def stop(self) -> None:
        if self._camera is not None:
            self._camera.stop()
            self._camera = None
            self._session = None
        self._stack.setCurrentWidget(self._placeholder)

    def set_enabled(self, enabled: bool) -> bool:
        if enabled:
            return self.start()
        self.stop()
        return False

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._badge.adjustSize()
        self._badge.move(14, self.height() - self._badge.height() - 12)
        self._badge.raise_()
        self._bars.move(
            self.width() - self._bars.width() - 14,
            self.height() - self._bars.height() - 12,
        )
        self._bars.raise_()


class SpeakerFrame(Panel):
    """给发言人瓦片加一圈随说话状态亮起的描边。"""

    def __init__(self, inner: QWidget, *, accent: str) -> None:
        super().__init__(object_name="SpeakerFrame")
        self._accent = accent
        self._active = False
        layout = QHBoxLayout(self)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.addWidget(inner)
        self._render()

    def set_active(self, active: bool) -> None:
        if active != self._active:
            self._active = active
            self._render()

    def _render(self) -> None:
        border = self._accent if self._active else "transparent"
        self.setStyleSheet(
            f"#SpeakerFrame {{ border: 2px solid {border}; border-radius: 17px; background: transparent; }}"
        )
