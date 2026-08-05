from __future__ import annotations

from PySide6.QtGui import QColor


class Color:
    """浅色设计令牌。白底 + 冷灰层次 + 单一靛紫强调色，参照现代 SaaS 的克制配色。

    层次规则：画布(BG) 最浅灰 → 卡片(SURFACE) 纯白 → 嵌套块(SURFACE_SUBTLE) 回到浅灰。
    不用投影表达层次，只用 1px 边框与底色差，渲染更稳、观感更干净。
    """

    # 画布与表面
    BG = "#F7F8FA"
    BG_ELEVATED = "#FFFFFF"
    SURFACE = "#FFFFFF"
    SURFACE_SUBTLE = "#F7F8FA"
    SURFACE_HOVER = "#F2F3F7"
    SURFACE_ACTIVE = "#E9EBF0"

    # 描边
    BORDER = "#E4E6EC"
    BORDER_STRONG = "#D2D5DE"
    BORDER_FOCUS = "#B9BEF0"

    # 强调色
    PRIMARY = "#5B5BD6"
    PRIMARY_HOVER = "#6E6EE0"
    PRIMARY_PRESSED = "#4B4BC0"
    PRIMARY_SOFT = "#EEEEFB"
    PRIMARY_TEXT = "#4A4AC4"

    # 语义色（均按浅底可读性挑选）
    ACCENT = "#0E94A8"
    ACCENT_SOFT = "#E6F6F8"
    DANGER = "#DC2B3E"
    DANGER_HOVER = "#E8465A"
    DANGER_SOFT = "#FDECEE"
    SUCCESS = "#0F8A5F"
    SUCCESS_SOFT = "#E6F5EE"
    WARNING = "#B4690E"
    WARNING_SOFT = "#FDF3E3"
    INFO = "#2563C9"
    INFO_SOFT = "#EAF1FD"

    # 文本
    TEXT = "#16181D"
    TEXT_MUTED = "#5C6270"
    TEXT_FAINT = "#8A90A0"
    TEXT_ON_PRIMARY = "#FFFFFF"

    # 复盘批注
    STRENGTH = "#0F8A5F"
    WEAKNESS = "#DC2B3E"
    FILLER = "#B4690E"
    OFF_TOPIC = "#7C4DDB"

    # 会话双方
    INTERVIEWER = "#5B5BD6"
    CANDIDATE = "#0E94A8"
    INTERVIEWER_SOFT = "#F1F1FC"
    CANDIDATE_SOFT = "#EAF7F9"

    # 视频舞台（浅色 UI 中的深色专注区，视频与光球在深底上更清晰）
    STAGE_BG = "#15171C"
    STAGE_BORDER = "#2A2E38"
    STAGE_TEXT = "#F0F1F5"
    STAGE_TEXT_MUTED = "#9BA1B0"

    # 代码高亮（浅底专用，保证对比度）
    CODE_BG = "#FBFBFD"
    CODE_KEYWORD = "#7C3AED"
    CODE_STRING = "#0F8A5F"
    CODE_NUMBER = "#B4690E"
    CODE_COMMENT = "#98A0B0"
    CODE_FUNC = "#2563C9"
    CODE_LINE_HL = "#F2F3F7"


DIMENSION_COLORS: tuple[str, ...] = (
    "#5B5BD6",
    "#0E94A8",
    "#B4690E",
    "#7C4DDB",
    "#DC2B3E",
    "#0F8A5F",
)

FONT_FAMILY = '"Segoe UI Variable Text", "Segoe UI", "Microsoft YaHei UI", "PingFang SC", sans-serif'
MONO_FAMILY = '"Cascadia Code", "JetBrains Mono", "Consolas", monospace'

RADIUS = 10
RADIUS_SM = 6
RADIUS_LG = 14


def qcolor(hex_str: str, alpha: int = 255) -> QColor:
    color = QColor(hex_str)
    color.setAlpha(alpha)
    return color


def build_stylesheet() -> str:
    c = Color
    return f"""
* {{
    font-family: {FONT_FAMILY};
    font-size: 14px;
    color: {c.TEXT};
    outline: none;
}}

QWidget#Root, QMainWindow {{
    background-color: {c.BG};
}}

QWidget {{
    background-color: transparent;
}}

QStackedWidget#ViewStack {{
    background-color: {c.BG};
}}

QWidget#TopBar {{
    background-color: {c.SURFACE};
    border-bottom: 1px solid {c.BORDER};
}}

QToolTip {{
    background-color: {c.TEXT};
    color: #FFFFFF;
    border: none;
    border-radius: {RADIUS_SM}px;
    padding: 6px 10px;
    font-size: 12px;
}}

QScrollArea, QScrollArea > QWidget > QWidget {{
    background: transparent;
    border: none;
}}

QScrollBar:vertical {{
    background: transparent;
    width: 12px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {c.BORDER_STRONG};
    border-radius: 5px;
    min-height: 36px;
}}
QScrollBar::handle:vertical:hover {{ background: {c.TEXT_FAINT}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}

QScrollBar:horizontal {{
    background: transparent;
    height: 12px;
    margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background: {c.BORDER_STRONG};
    border-radius: 5px;
    min-width: 36px;
}}
QScrollBar::handle:horizontal:hover {{ background: {c.TEXT_FAINT}; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: transparent; }}

QLabel {{ background: transparent; }}
QLabel#PageTitle {{ font-size: 32px; font-weight: 700; color: {c.TEXT}; }}
QLabel#Lead {{ font-size: 15px; color: {c.TEXT_MUTED}; }}
QLabel#H1 {{ font-size: 26px; font-weight: 700; color: {c.TEXT}; }}
QLabel#H2 {{ font-size: 19px; font-weight: 650; color: {c.TEXT}; }}
QLabel#H3 {{ font-size: 15px; font-weight: 650; color: {c.TEXT}; }}
QLabel#Muted {{ color: {c.TEXT_MUTED}; }}
QLabel#Faint {{ color: {c.TEXT_FAINT}; font-size: 13px; }}
QLabel#Metric {{ font-size: 34px; font-weight: 700; color: {c.TEXT}; }}
QPushButton {{
    background-color: {c.SURFACE};
    color: {c.TEXT};
    border: 1px solid {c.BORDER_STRONG};
    border-radius: {RADIUS}px;
    padding: 9px 18px;
    font-weight: 600;
}}
QPushButton:hover {{
    background-color: {c.SURFACE_HOVER};
    border-color: {c.TEXT_FAINT};
}}
QPushButton:pressed {{ background-color: {c.SURFACE_ACTIVE}; }}
QPushButton:disabled {{
    color: {c.TEXT_FAINT};
    background-color: {c.SURFACE_SUBTLE};
    border-color: {c.BORDER};
}}

QPushButton#Primary {{
    background-color: {c.PRIMARY};
    color: {c.TEXT_ON_PRIMARY};
    border: 1px solid {c.PRIMARY};
}}
QPushButton#Primary:hover {{ background-color: {c.PRIMARY_HOVER}; border-color: {c.PRIMARY_HOVER}; }}
QPushButton#Primary:pressed {{ background-color: {c.PRIMARY_PRESSED}; border-color: {c.PRIMARY_PRESSED}; }}
QPushButton#Primary:disabled {{
    background-color: {c.PRIMARY_SOFT};
    border-color: {c.PRIMARY_SOFT};
    color: {c.TEXT_FAINT};
}}

QPushButton#Danger {{
    background-color: {c.DANGER};
    color: {c.TEXT_ON_PRIMARY};
    border: 1px solid {c.DANGER};
}}
QPushButton#Danger:hover {{ background-color: {c.DANGER_HOVER}; border-color: {c.DANGER_HOVER}; }}
QPushButton#Danger:pressed {{ background-color: {c.DANGER}; }}
QPushButton#Danger:disabled {{
    background-color: {c.DANGER_SOFT};
    border-color: {c.DANGER_SOFT};
    color: {c.TEXT_FAINT};
}}

QPushButton#Ghost {{
    background-color: transparent;
    border: 1px solid {c.BORDER_STRONG};
    color: {c.TEXT_MUTED};
}}
QPushButton#Ghost:hover {{
    background-color: {c.SURFACE_HOVER};
    color: {c.TEXT};
    border-color: {c.TEXT_FAINT};
}}
QPushButton#Ghost:pressed {{ background-color: {c.SURFACE_ACTIVE}; }}

QPushButton#Choice {{
    background-color: {c.SURFACE};
    border: 1px solid {c.BORDER_STRONG};
    color: {c.TEXT_MUTED};
    padding: 0 16px;
}}
QPushButton#Choice:hover {{
    background-color: {c.SURFACE_HOVER};
    border-color: {c.TEXT_FAINT};
    color: {c.TEXT};
}}
QPushButton#Choice:checked {{
    background-color: {c.PRIMARY_SOFT};
    border: 1px solid {c.PRIMARY};
    color: {c.PRIMARY_TEXT};
}}

QPushButton#Link {{
    background: transparent;
    border: none;
    color: {c.PRIMARY_TEXT};
    padding: 4px 6px;
    font-weight: 600;
}}
QPushButton#Link:hover {{ color: {c.PRIMARY_HOVER}; }}
QPushButton#Link:pressed {{ color: {c.PRIMARY_PRESSED}; }}

QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QComboBox {{
    background-color: {c.SURFACE};
    border: 1px solid {c.BORDER_STRONG};
    border-radius: {RADIUS}px;
    padding: 9px 12px;
    color: {c.TEXT};
    selection-background-color: {c.PRIMARY};
    selection-color: {c.TEXT_ON_PRIMARY};
}}
QLineEdit:hover, QTextEdit:hover, QPlainTextEdit:hover, QComboBox:hover {{
    border-color: {c.TEXT_FAINT};
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QComboBox:focus {{
    border-color: {c.PRIMARY};
}}
QLineEdit:disabled, QComboBox:disabled, QPlainTextEdit:disabled {{
    color: {c.TEXT_FAINT};
    background-color: {c.SURFACE_SUBTLE};
}}
QLineEdit::placeholder {{ color: {c.TEXT_FAINT}; }}

QComboBox::drop-down {{ border: none; width: 28px; }}
QComboBox::down-arrow {{
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {c.TEXT_MUTED};
    margin-right: 12px;
}}
QComboBox QAbstractItemView {{
    background-color: {c.SURFACE};
    border: 1px solid {c.BORDER_STRONG};
    border-radius: {RADIUS_SM}px;
    padding: 4px;
    selection-background-color: {c.PRIMARY_SOFT};
    selection-color: {c.PRIMARY_TEXT};
    outline: none;
}}

QSpinBox::up-button, QSpinBox::down-button {{ width: 0; border: none; }}

QCheckBox {{ spacing: 8px; background: transparent; color: {c.TEXT_MUTED}; }}
QCheckBox:hover {{ color: {c.TEXT}; }}
QCheckBox::indicator {{
    width: 17px; height: 17px;
    border: 1px solid {c.BORDER_STRONG};
    border-radius: 5px;
    background-color: {c.SURFACE};
}}
QCheckBox::indicator:hover {{ border-color: {c.PRIMARY}; }}
QCheckBox::indicator:checked {{
    background-color: {c.PRIMARY};
    border-color: {c.PRIMARY};
    image: none;
}}

QSlider::groove:horizontal {{
    height: 4px;
    background: {c.SURFACE_ACTIVE};
    border-radius: 2px;
}}
QSlider::sub-page:horizontal {{ background: {c.PRIMARY}; border-radius: 2px; }}
QSlider::handle:horizontal {{
    background: {c.SURFACE};
    border: 2px solid {c.PRIMARY};
    width: 14px; height: 14px;
    margin: -6px 0;
    border-radius: 9px;
}}
QSlider::handle:horizontal:hover {{ border-color: {c.PRIMARY_HOVER}; }}
QSlider::handle:horizontal:pressed {{ background: {c.PRIMARY_SOFT}; }}

QProgressBar {{
    background-color: {c.SURFACE_ACTIVE};
    border: none;
    border-radius: 4px;
    height: 8px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{ background-color: {c.PRIMARY}; border-radius: 4px; }}

QTabWidget::pane {{ border: none; }}
QTabBar::tab {{
    background: transparent;
    color: {c.TEXT_MUTED};
    padding: 9px 18px;
    border-bottom: 2px solid transparent;
    font-weight: 600;
}}
QTabBar::tab:selected {{ color: {c.TEXT}; border-bottom-color: {c.PRIMARY}; }}
QTabBar::tab:hover {{ color: {c.TEXT}; }}

QSplitter::handle {{ background: transparent; }}
QSplitter::handle:hover {{ background: {c.BORDER}; }}

QMenu {{
    background-color: {c.SURFACE};
    border: 1px solid {c.BORDER_STRONG};
    border-radius: {RADIUS_SM}px;
    padding: 6px;
}}
QMenu::item {{ padding: 8px 24px; border-radius: 5px; color: {c.TEXT_MUTED}; }}
QMenu::item:selected {{ background-color: {c.PRIMARY_SOFT}; color: {c.PRIMARY_TEXT}; }}

QDialog {{ background-color: {c.BG}; }}
"""
