from __future__ import annotations

from collections.abc import Callable

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QHBoxLayout, QMainWindow, QWidget


class AppWindow(QMainWindow):
    """主窗口。使用原生窗口框架，缩放、移动、多屏、任务栏均由系统托管，稳定可靠。"""

    def __init__(self, *, title: str) -> None:
        super().__init__()
        self.setWindowTitle(title)
        self._content = QWidget()
        self._content.setObjectName("Root")
        self.setCentralWidget(self._content)

    def content_host(self) -> QWidget:
        return self._content

    def set_title_actions(self, builder: Callable[[QHBoxLayout], None]) -> None:  # pragma: no cover
        """保留接口以兼容调用方；原生框架下无自定义标题栏动作。"""
        return

    def present(self, *, desired_width: int = 1360, desired_height: int = 880) -> None:
        """按屏幕可用区域自适应显示：屏幕不够大就最大化，避免窗口超出可视范围。"""
        screen = self.screen() or QGuiApplication.primaryScreen()
        available = screen.availableGeometry() if screen else None
        if available is not None and (
            available.width() < desired_width + 40 or available.height() < desired_height + 40
        ):
            self.showMaximized()
        else:
            self.resize(desired_width, desired_height)
            if available is not None:
                frame = self.frameGeometry()
                frame.moveCenter(available.center())
                self.move(frame.topLeft())
            self.show()
        self.raise_()
        self.activateWindow()
