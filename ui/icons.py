"""
Small monochrome icon set used throughout the UI instead of emoji characters.

Icons are plain inline SVG strings rendered to QIcon at runtime via
QtSvg/QPainter, so there are no external image assets to ship or manage.
"""

from PyQt6.QtCore import QByteArray, QSize, Qt
from PyQt6.QtGui import QIcon, QPixmap, QPainter
from PyQt6.QtSvg import QSvgRenderer

_STROKE = "#d4d4d4"

_SVG_TEMPLATES: dict[str, str] = {
    "cloud": f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{_STROKE}" stroke-width="2"><path d="M17 18H6a4 4 0 1 1 .9-7.9A5.5 5.5 0 0 1 17 9.5 3.5 3.5 0 0 1 17 18z"/></svg>',
    "cpu": f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{_STROKE}" stroke-width="2"><rect x="6" y="6" width="12" height="12" rx="1"/><path d="M9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3"/></svg>',
    "terminal": f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{_STROKE}" stroke-width="2"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 9l3 3-3 3M13 15h4"/></svg>',
    "settings": f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{_STROKE}" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .34 1.87l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.7 1.7 0 0 0-1.87-.34 1.7 1.7 0 0 0-1 1.55V21a2 2 0 1 1-4 0v-.09A1.7 1.7 0 0 0 9 19.4a1.7 1.7 0 0 0-1.87.34l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.7 1.7 0 0 0 4.6 15a1.7 1.7 0 0 0-1.55-1H3a2 2 0 1 1 0-4h.09A1.7 1.7 0 0 0 4.6 9a1.7 1.7 0 0 0-.34-1.87l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.7 1.7 0 0 0 9 4.6a1.7 1.7 0 0 0 1-1.55V3a2 2 0 1 1 4 0v.09a1.7 1.7 0 0 0 1 1.55 1.7 1.7 0 0 0 1.87-.34l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.7 1.7 0 0 0 19.4 9a1.7 1.7 0 0 0 1.55 1H21a2 2 0 1 1 0 4h-.09a1.7 1.7 0 0 0-1.51 1z"/></svg>',
    "bug": f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{_STROKE}" stroke-width="2"><rect x="8" y="7" width="8" height="12" rx="4"/><path d="M12 2v5M5 10H2M5 16H2M22 10h-3M22 16h-3M8 10 5 7M16 10l3-3M8 16l-3 3M16 16l3 3"/></svg>',
    "chart": f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{_STROKE}" stroke-width="2"><path d="M3 3v18h18"/><path d="M7 15l3-4 3 3 5-7"/></svg>',
    "puzzle": f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{_STROKE}" stroke-width="2"><path d="M19.4 15a1.7 1.7 0 0 0 1.6-1.7V10a2 2 0 0 0-2-2h-2.3a1.7 1.7 0 0 1-1.6-2.4 1.7 1.7 0 1 0-3.2 0A1.7 1.7 0 0 1 10 8H7.7a2 2 0 0 0-2 2v2.3a1.7 1.7 0 0 1-2.4 1.6 1.7 1.7 0 1 0 0 3.2A1.7 1.7 0 0 1 5.7 19H8a2 2 0 0 0 2-2v-2.3a1.7 1.7 0 0 1 2.4-1.6 1.7 1.7 0 1 0 3.2 0 1.7 1.7 0 0 1 1.6-1.1H19a2 2 0 0 0 2-2"/></svg>',
    "upload": f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{_STROKE}" stroke-width="2"><path d="M12 16V4M6 10l6-6 6 6M4 20h16"/></svg>',
    "send": f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{_STROKE}" stroke-width="2"><path d="M22 2 11 13M22 2l-7 20-4-9-9-4 20-7z"/></svg>',
    "stop": f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{_STROKE}" stroke-width="2"><rect x="5" y="5" width="14" height="14" rx="2"/></svg>',
    "trash": f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{_STROKE}" stroke-width="2"><path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2m3 0-1 14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2L4 6"/></svg>',
    "help": f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{_STROKE}" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M9.1 9a3 3 0 0 1 5.8 1c0 2-3 2-3 4M12 17h.01"/></svg>',
    "plus": f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{_STROKE}" stroke-width="2"><path d="M12 5v14M5 12h14"/></svg>',
    "history": f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{_STROKE}" stroke-width="2"><path d="M3 3v5h5"/><path d="M3.05 13A9 9 0 1 0 6 5.3L3 8"/><path d="M12 7v5l4 2"/></svg>',
    "edit": f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{_STROKE}" stroke-width="2"><path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5z"/></svg>',
    "chat": f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{_STROKE}" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>',
}


def get_icon(name: str, color: str | None = None, size: int = 20) -> QIcon:
    """Return a QIcon rendered from an embedded SVG template."""
    svg = _SVG_TEMPLATES.get(name)
    if svg is None:
        return QIcon()
    if color:
        svg = svg.replace(_STROKE, color)

    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pixmap = QPixmap(QSize(size, size))
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return QIcon(pixmap)

