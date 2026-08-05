from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from .theme import Color

# 24x24 网格、2px 描边、圆角端点。统一线性风格，避免符号混搭的廉价感。
_PATHS: dict[str, str] = {
    "dashboard": (
        '<rect x="3" y="3" width="7.5" height="7.5" rx="2"/>'
        '<rect x="13.5" y="3" width="7.5" height="7.5" rx="2"/>'
        '<rect x="3" y="13.5" width="7.5" height="7.5" rx="2"/>'
        '<rect x="13.5" y="13.5" width="7.5" height="7.5" rx="2"/>'
    ),
    "prepare": (
        '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/>'
        '<path d="M14 3v5h5"/><path d="M9 13h6"/><path d="M9 17h4"/>'
    ),
    "persona": (
        '<path d="M4 6h9"/><path d="M18 6h2"/><circle cx="15.5" cy="6" r="2.2"/>'
        '<path d="M4 12h3"/><path d="M12 12h8"/><circle cx="9.5" cy="12" r="2.2"/>'
        '<path d="M4 18h9"/><path d="M18 18h2"/><circle cx="15.5" cy="18" r="2.2"/>'
    ),
    "mistakes": (
        '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/>'
        '<path d="M6.5 3H20v18H6.5A2.5 2.5 0 0 1 4 18.5v-13A2.5 2.5 0 0 1 6.5 3z"/>'
        '<path d="M9 8h7"/>'
    ),
    "growth": '<path d="M3 17.5l6-6 4 4 7.5-7.5"/><path d="M14.5 8h6v6"/>',
    "settings": (
        '<circle cx="12" cy="12" r="3.2"/>'
        '<path d="M12 2.5v3M12 18.5v3M4.6 4.6l2.1 2.1M17.3 17.3l2.1 2.1'
        'M2.5 12h3M18.5 12h3M4.6 19.4l2.1-2.1M17.3 6.7l2.1-2.1"/>'
    ),
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "chevron_right": '<path d="M9.5 5.5l6.5 6.5-6.5 6.5"/>',
    "chevron_left": '<path d="M14.5 5.5L8 12l6.5 6.5"/>',
    "chevron_down": '<path d="M5.5 9.5l6.5 6.5 6.5-6.5"/>',
    "check": '<path d="M4.5 12.5l5 5 10-11"/>',
    "send": '<path d="M21 3L10.5 13.5"/><path d="M21 3l-7 18-3.5-7.5L3 10z"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7.5v5l3.5 2"/>',
    "check_circle": '<circle cx="12" cy="12" r="9"/><path d="M8 12.4l2.6 2.6L16.2 9.4"/>',
    "award": '<circle cx="12" cy="8.5" r="5.5"/><path d="M8.8 13.4L7 22l5-2.8 5 2.8-1.8-8.6"/>',
    "activity": '<path d="M3 12h3.5l2.5-7 4 14 2.5-7H21"/>',
    "target": (
        '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/>'
        '<circle cx="12" cy="12" r="1.4"/>'
    ),
    "layers": (
        '<path d="M12 2.5l9 5-9 5-9-5z"/><path d="M3 12.5l9 5 9-5"/>'
        '<path d="M3 17l9 5 9-5"/>'
    ),
    "mic": (
        '<rect x="9" y="2.5" width="6" height="11" rx="3"/>'
        '<path d="M5 11.5a7 7 0 0 0 14 0"/><path d="M12 18.5v3"/>'
    ),
    "mic_off": (
        '<rect x="9" y="2.5" width="6" height="11" rx="3"/>'
        '<path d="M5 11.5a7 7 0 0 0 14 0"/><path d="M12 18.5v3"/>'
        '<path d="M3.5 3.5l17 17"/>'
    ),
    "video": '<rect x="2.5" y="6" width="13" height="12" rx="2.5"/><path d="M15.5 10.5l6-3.5v10l-6-3.5z"/>',
    "video_off": (
        '<rect x="2.5" y="6" width="13" height="12" rx="2.5"/>'
        '<path d="M15.5 10.5l6-3.5v10l-6-3.5z"/><path d="M3.5 3.5l17 17"/>'
    ),
    "code": '<path d="M9 18l-6-6 6-6"/><path d="M15 6l6 6-6 6"/>',
    "zap": '<path d="M13 2.5L4.5 13.5H10L9 21.5l8.5-11H12z"/>',
    "exit": (
        '<path d="M9.5 21H5.5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/>'
        '<path d="M16 16.5l4.5-4.5L16 7.5"/><path d="M20.5 12H9"/>'
    ),
    "upload": (
        '<path d="M20.5 15.5v3.5a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2v-3.5"/>'
        '<path d="M7.5 8.5L12 4l4.5 4.5"/><path d="M12 4v12"/>'
    ),
    "download": (
        '<path d="M20.5 15.5v3.5a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2v-3.5"/>'
        '<path d="M7.5 11.5L12 16l4.5-4.5"/><path d="M12 16V4"/>'
    ),
    "sparkles": (
        '<path d="M12 3l1.7 4.6L18.3 9.3 13.7 11 12 15.6 10.3 11 5.7 9.3 10.3 7.6z"/>'
        '<path d="M18.5 15l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8z"/>'
    ),
    "warning": (
        '<path d="M10.3 4L2 18a2 2 0 0 0 1.7 3h16.6a2 2 0 0 0 1.7-3L13.7 4a2 2 0 0 0-3.4 0z"/>'
        '<path d="M12 9.5v4"/><path d="M12 17.2h.01"/>'
    ),
    "user": '<circle cx="12" cy="8" r="4"/><path d="M4.5 20.5c0-4 3.4-6 7.5-6s7.5 2 7.5 6"/>',
    "bulb": (
        '<path d="M9.5 18.5h5"/><path d="M10.5 21.5h3"/>'
        '<path d="M12 2.5a6.8 6.8 0 0 0-4 12.3v1.7h8v-1.7A6.8 6.8 0 0 0 12 2.5z"/>'
    ),
    "trash": (
        '<path d="M3.5 6.5h17"/><path d="M8.5 6.5V4.6a1.5 1.5 0 0 1 1.5-1.5h4a1.5 1.5 0 0 1 1.5 1.5v1.9"/>'
        '<path d="M18.5 6.5l-1 13.4a2 2 0 0 1-2 1.6H8.5a2 2 0 0 1-2-1.6l-1-13.4"/>'
    ),
    "refresh": '<path d="M20.5 12a8.5 8.5 0 1 1-2.9-6.4"/><path d="M20.5 3.5v5.5H15"/>',
    "copy": (
        '<rect x="8.5" y="8.5" width="12" height="12" rx="2.5"/>'
        '<path d="M15.5 5.5v-1a2 2 0 0 0-2-2h-8a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h1"/>'
    ),
    "save": (
        '<path d="M19.5 21.5h-15a2 2 0 0 1-2-2v-15a2 2 0 0 1 2-2h11l6 6v11a2 2 0 0 1-2 2z"/>'
        '<path d="M7 21.5v-7h10v7"/><path d="M7 2.5v5h7"/>'
    ),
    "search": '<circle cx="10.5" cy="10.5" r="7"/><path d="M15.6 15.6l5 5"/>',
    "calendar": (
        '<rect x="3" y="5" width="18" height="16" rx="2.5"/><path d="M3 10h18"/>'
        '<path d="M8 3v4M16 3v4"/>'
    ),
    "message": '<path d="M21 11.5a8 8 0 0 1-8.5 8L7 21.5l1-3.6A8 8 0 1 1 21 11.5z"/>',
    "shield": '<path d="M12 2.5l8 3v6c0 5-3.4 8.6-8 10-4.6-1.4-8-5-8-10v-6z"/><path d="M9 12l2.2 2.2L15.2 10"/>',
    "flame": (
        '<path d="M12 22c4 0 6.5-2.7 6.5-6.2 0-4.6-4.3-6.3-4.3-10.3 0 0-2.2 1-3.2 3.6'
        '-.9-1-1.4-2.4-1.4-2.4C7.9 8.4 5.5 10.6 5.5 15c0 4 3 7 6.5 7z"/>'
    ),
    "pause": (
        '<rect x="7" y="4.5" width="3.6" height="15" rx="1.5"/>'
        '<rect x="13.4" y="4.5" width="3.6" height="15" rx="1.5"/>'
    ),
    "play": '<path d="M7 4.5l12 7.5-12 7.5z"/>',
}

_FILLED = {"play", "zap", "sparkles", "flame", "pause"}

_TEMPLATE = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
    'fill="{fill}" stroke="{stroke}" stroke-width="{width}" '
    'stroke-linecap="round" stroke-linejoin="round">{body}</svg>'
)


@lru_cache(maxsize=512)
def pixmap(name: str, *, size: int = 20, color: str = Color.TEXT_MUTED, width: float = 1.9) -> QPixmap:
    body = _PATHS.get(name)
    if body is None:
        raise KeyError(f"未知图标: {name}")
    filled = name in _FILLED
    svg = _TEMPLATE.format(
        fill=color if filled else "none",
        stroke="none" if filled else color,
        width=width,
        body=body,
    )
    renderer = QSvgRenderer(svg.encode("utf-8"))
    canvas = QPixmap(size, size)
    canvas.fill(Qt.GlobalColor.transparent)
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter)
    painter.end()
    return canvas


def icon(name: str, *, size: int = 20, color: str = Color.TEXT_MUTED, width: float = 1.9) -> QIcon:
    return QIcon(pixmap(name, size=size, color=color, width=width))


def icon_size(size: int = 20) -> QSize:
    return QSize(size, size)
