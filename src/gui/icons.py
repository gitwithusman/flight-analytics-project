"""Small built-in line-icon set rendered from inline SVG.

Drawing icons from vector paths keeps them crisp at every display scale and
avoids relying on emoji/symbol glyphs, which differ between fonts and
platforms.
"""

from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QGuiApplication, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

# 24x24 stroke icons (stroke colour is substituted at render time).
_PATHS = {
    "overview": '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
    "flights": '<path d="M3 17l8-3 5 6 2-1-3-7 5-3c1-1 1-2 0-2s-2 0-3 1l-4 3-7-3-2 1 5 4-3 2-2-1z"/>',
    "airports": '<path d="M12 21s-7-6.2-7-11.5A7 7 0 0 1 19 9.5C19 14.8 12 21 12 21z"/><circle cx="12" cy="9.5" r="2.5"/>',
    "explorer": '<circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/>',
    "delays": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "weather": '<path d="M7 18a4 4 0 0 1-.5-8A6 6 0 0 1 18 9.5a4.2 4.2 0 0 1-.5 8.5z"/>',
    "data": '<ellipse cx="12" cy="5.5" rx="8" ry="3"/><path d="M4 5.5v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6M4 11.5v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6"/>',
    "settings": '<path d="M4 7h9M17 7h3M4 17h3M11 17h9"/><circle cx="15" cy="7" r="2"/><circle cx="9" cy="17" r="2"/>',
    "about": '<circle cx="12" cy="12" r="9"/><path d="M12 11v6"/><circle cx="12" cy="7.6" r="0.6"/>',
    "search": '<circle cx="11" cy="11" r="6"/><path d="M16 16l5 5"/>',
    "compare": '<rect x="3" y="4" width="7" height="16" rx="1.5"/><rect x="14" y="4" width="7" height="16" rx="1.5"/>',
    "map": '<path d="M3 6l6-2 6 2 6-2v14l-6 2-6-2-6 2z"/><path d="M9 4v14M15 6v14"/>',
    "etl": '<path d="M4 5h6v4H4zM14 5h6v4h-6zM14 15h6v4h-6z"/><path d="M10 7h4M7 9v8h7"/>',
    "report": '<path d="M6 3h9l4 4v14H6z"/><path d="M14 3v5h5M9 13h7M9 17h7"/>',
    "refresh": '<path d="M20 11a8 8 0 0 0-14.5-3.5L4 9"/><path d="M4 4v5h5"/><path d="M4 13a8 8 0 0 0 14.5 3.5L20 15"/><path d="M20 20v-5h-5"/>',
    "download": '<path d="M12 4v11"/><path d="M7 10.5l5 5 5-5"/><path d="M5 20h14"/>',
    "check": '<circle cx="12" cy="12" r="9"/><path d="M8 12.5l2.7 2.7L16 9.5"/>',
    "alert": '<path d="M12 3l10 18H2z"/><path d="M12 10v5"/><circle cx="12" cy="18" r="0.6"/>',
    "error": '<circle cx="12" cy="12" r="9"/><path d="M12 7v6"/><circle cx="12" cy="16.5" r="0.6"/>',
    "close": '<path d="M6 6l12 12M18 6L6 18"/>',
    "inbox": '<path d="M3 13l3-8h12l3 8v6H3z"/><path d="M3 13h5l1 3h6l1-3h5"/>',
    "menu": '<path d="M4 7h16M4 12h16M4 17h16"/>',
    "clear": '<circle cx="12" cy="12" r="9"/><path d="M9 9l6 6M15 9l-6 6"/>',
}


def _svg(name: str, color: str) -> bytes:
    body = _PATHS[name]
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
        f'fill="none" stroke="{color}" stroke-width="1.8" '
        f'stroke-linecap="round" stroke-linejoin="round">{body}</svg>'
    ).encode()


@lru_cache(maxsize=256)
def pixmap(name: str, color: str, size: int = 18) -> QPixmap:
    """Render an icon to a pixmap sharp on high-DPI screens."""
    ratio = 1.0
    screen = QGuiApplication.primaryScreen()
    if screen is not None:
        ratio = max(1.0, screen.devicePixelRatio())
    px = int(size * ratio)
    pm = QPixmap(px, px)
    pm.fill(Qt.GlobalColor.transparent)
    renderer = QSvgRenderer(QByteArray(_svg(name, color)))
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter, QRectF(0, 0, px, px))
    painter.end()
    pm.setDevicePixelRatio(ratio)
    return pm


def icon(name: str, color: str, checked_color: str | None = None,
         size: int = 18) -> QIcon:
    """Return a QIcon; ``checked_color`` is used while a button is checked."""
    result = QIcon()
    result.addPixmap(pixmap(name, color, size), QIcon.Mode.Normal, QIcon.State.Off)
    result.addPixmap(pixmap(name, checked_color or color, size),
                     QIcon.Mode.Normal, QIcon.State.On)
    return result
