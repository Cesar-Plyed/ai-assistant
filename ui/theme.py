"""Design tokens and the single global stylesheet (Dark / Light / System)."""

from __future__ import annotations

from typing import Any

FONT_UI = "'Inter', 'Segoe UI', system-ui, sans-serif"
FONT_MONO = "'JetBrains Mono', 'Fira Code', monospace"

SPACING = {"xs": 4, "sm": 8, "md": 12, "lg": 16}
RADII = {"sm": 4, "md": 6, "lg": 8}
MOTION = {"fast": 120, "normal": 240}
MIN_CONTROL_HEIGHT = 32

DARK: dict[str, str] = {
    "bg": "#1a1b26", "surface": "#24283b", "text": "#c0caf5", "muted": "#8a93c4",
    "primary": "#7aa2f7", "on_primary": "#1a1b26", "success": "#9ece6a",
    "warning": "#e0af68", "error": "#f7768e", "border": "#2f3347", "hover": "#2f3347",
    "info": "#7dcfff", "accent2": "#bb9af7", "log_text": "#a9b1d6",
}
LIGHT: dict[str, str] = {
    "bg": "#f5f6fa", "surface": "#ffffff", "text": "#1f2335", "muted": "#5a6182",
    "primary": "#2e5bd8", "on_primary": "#ffffff", "success": "#2f7d32",
    "warning": "#8a5a00", "error": "#b3261e", "border": "#c9cde0", "hover": "#e6e9f5",
    "info": "#00677f", "accent2": "#6b3fb8", "log_text": "#3b4261",
}
THEMES = {"dark": DARK, "light": LIGHT}

_current_name = "dark"


def detect_system_theme() -> str:
    """Return "dark" or "light" from Qt's colour-scheme hint (dark if unknown)."""
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QGuiApplication

        hints = QGuiApplication.styleHints()
        scheme = hints.colorScheme()
        if scheme == Qt.ColorScheme.Light:
            return "light"
    except Exception:
        pass
    return "dark"


def resolve_theme(setting: str | None) -> str:
    name = (setting or "dark").lower()
    if name == "system":
        return detect_system_theme()
    return name if name in THEMES else "dark"


def tokens(name: str | None = None) -> dict[str, str]:
    return dict(THEMES[name or _current_name])


def current_name() -> str:
    return _current_name


def _luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))

    def lin(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def contrast_ratio(fg: str, bg: str) -> float:
    a, b = _luminance(fg), _luminance(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


def build_stylesheet(t: dict[str, str]) -> str:
    r, minh = RADII, MIN_CONTROL_HEIGHT
    return f"""
    QMainWindow, QDialog, QMessageBox, QInputDialog {{
        background-color: {t['bg']}; color: {t['text']}; font-family: {FONT_UI};
    }}
    QLabel {{ color: {t['text']}; font-family: {FONT_UI}; background: transparent; }}
    QLabel[muted="true"] {{ color: {t['muted']}; }}
    QCheckBox, QRadioButton {{ color: {t['text']}; spacing: 8px; font-family: {FONT_UI}; min-height: {minh}px; }}
    QCheckBox::indicator, QRadioButton::indicator {{
        width: 16px; height: 16px; border: 1px solid {t['muted']};
        border-radius: {r['sm']}px; background-color: {t['surface']};
    }}
    QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
        background-color: {t['primary']}; border-color: {t['primary']};
    }}
    QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
        background-color: {t['surface']}; color: {t['text']};
        border: 1px solid {t['border']}; border-radius: {r['md']}px;
        padding: 6px 10px; font-family: {FONT_UI}; font-size: 14px;
        min-height: {minh - 14}px;
        selection-background-color: {t['primary']}; selection-color: {t['on_primary']};
    }}
    QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus,
    QDoubleSpinBox:focus, QComboBox:focus {{ border: 2px solid {t['primary']}; }}
    QComboBox::drop-down {{ border: none; width: 0px; background: transparent; }}
    QComboBox QAbstractItemView {{
        background-color: {t['surface']}; color: {t['text']}; border: 1px solid {t['border']};
        selection-background-color: {t['primary']}; selection-color: {t['on_primary']}; outline: none;
    }}
    QPushButton {{
        background-color: {t['primary']}; color: {t['on_primary']}; border: none;
        border-radius: {r['md']}px; padding: 6px 16px; font-size: 14px; font-weight: 600;
        font-family: {FONT_UI}; min-height: {minh - 12}px;
    }}
    QPushButton:hover {{ background-color: {t['primary']}; border: 1px solid {t['text']}; }}
    QPushButton:pressed {{ background-color: {t['muted']}; }}
    QPushButton:focus {{ border: 2px solid {t['text']}; }}
    QPushButton:disabled {{ background-color: {t['border']}; color: {t['muted']}; }}
    QPushButton[secondary="true"], QDialog QPushButton {{
        background-color: {t['surface']}; color: {t['text']}; border: 1px solid {t['border']};
    }}
    QPushButton[secondary="true"]:hover, QDialog QPushButton:hover {{
        background-color: {t['hover']}; border-color: {t['muted']};
    }}
    QDialog QPushButton[text="Save and close"], QDialog QPushButton[text="Save"] {{
        background-color: {t['primary']}; color: {t['on_primary']}; border: none;
    }}
    QDialog QPushButton[text="Cancel"], QDialog QPushButton[text="&Cancel"],
    QDialog QPushButton[text="No"], QDialog QPushButton[text="&No"],
    QMessageBox QPushButton[text="Cancel"], QMessageBox QPushButton[text="&Cancel"] {{
        background-color: {t['error']}; color: {t['on_primary']}; border: none;
    }}
    QPushButton[danger="true"] {{ background-color: {t['error']}; color: {t['on_primary']}; border: none; }}
    QTextBrowser {{
        background-color: {t['bg']}; color: {t['text']}; border: 1px solid {t['border']};
        border-radius: {r['lg']}px; padding: 16px; font-size: 14px; font-family: {FONT_UI};
    }}
    QMenuBar {{ background-color: {t['bg']}; color: {t['text']}; font-family: {FONT_UI}; padding: 4px; }}
    QMenuBar::item:selected {{ background-color: {t['surface']}; border-radius: {r['sm']}px; }}
    QMenu {{
        background-color: {t['surface']}; color: {t['text']}; border: 1px solid {t['border']};
        border-radius: {r['md']}px; padding: 4px; font-family: {FONT_UI};
    }}
    QMenu::item {{ padding: 6px 16px; }}
    QMenu::item:selected {{ background-color: {t['primary']}; color: {t['on_primary']}; border-radius: {r['sm']}px; }}
    QDockWidget {{ color: {t['text']}; font-family: {FONT_UI}; }}
    QDockWidget::title {{ background-color: {t['surface']}; color: {t['text']}; padding: 8px 12px; font-weight: 600; }}
    QListWidget {{
        background-color: {t['bg']}; color: {t['text']}; border: 1px solid {t['border']};
        border-radius: {r['md']}px; font-family: {FONT_UI}; padding: 4px;
    }}
    QListWidget::item {{ padding: 6px 8px; border-radius: {r['sm']}px; }}
    QListWidget::item:selected {{ background-color: {t['primary']}; color: {t['on_primary']}; }}
    QListWidget::item:hover {{ background-color: {t['hover']}; }}
    QGroupBox {{
        color: {t['text']}; font-weight: 600; border: 1px solid {t['border']};
        border-radius: {r['lg']}px; margin-top: 12px; padding-top: 16px; font-family: {FONT_UI};
    }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 4px; }}
    QTabWidget::pane {{ border: 1px solid {t['border']}; border-radius: {r['md']}px; background-color: {t['bg']}; }}
    QTabBar::tab {{
        background-color: {t['surface']}; color: {t['muted']}; padding: 8px 16px;
        border: 1px solid {t['border']}; border-bottom: none;
        border-top-left-radius: {r['md']}px; border-top-right-radius: {r['md']}px; font-family: {FONT_UI};
    }}
    QTabBar::tab:selected {{ color: {t['text']}; background-color: {t['bg']}; }}
    QTabBar::tab:focus {{ border: 2px solid {t['primary']}; }}
    QProgressBar {{
        background-color: {t['surface']}; border: 1px solid {t['border']}; border-radius: {r['sm']}px;
        color: {t['text']}; text-align: center; font-family: {FONT_UI}; font-size: 11px; min-height: 16px;
    }}
    QProgressBar::chunk {{ background-color: {t['primary']}; border-radius: {r['sm']}px; }}
    QScrollBar:vertical {{ background-color: {t['bg']}; width: 12px; border-radius: 6px; margin: 0; }}
    QScrollBar::handle:vertical {{ background-color: {t['muted']}; border-radius: 6px; min-height: 30px; margin: 2px; }}
    QScrollBar::handle:vertical:hover {{ background-color: {t['primary']}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar:horizontal {{ background-color: {t['bg']}; height: 12px; border-radius: 6px; margin: 0; }}
    QScrollBar::handle:horizontal {{ background-color: {t['muted']}; border-radius: 6px; min-width: 30px; margin: 2px; }}
    QScrollBar::handle:horizontal:hover {{ background-color: {t['primary']}; }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
    QToolTip {{ background-color: {t['surface']}; color: {t['text']}; border: 1px solid {t['border']}; }}
    QListWidget#completionPopup {{
        background-color: {t['surface']}; border: 1px solid {t['border']};
        font-family: {FONT_MONO}; font-size: 12px;
    }}
    QFrame#attachmentChip {{
        background-color: {t['surface']}; border: 1px solid {t['border']}; border-radius: {r['md']}px;
    }}
    QWidget#composer {{
        background-color: {t['bg']};
    }}
    QLabel#attachmentBadge {{
        background-color: {t['primary']}; color: {t['on_primary']}; border-radius: 8px;
        padding: 0 5px; font-size: 11px; font-weight: 700;
    }}
    """


_listeners: list[Any] = []


def on_theme_changed(callback) -> None:
    _listeners.append(callback)


def apply_theme(app, setting: str | None = None) -> str:
    """Apply the theme globally; returns the resolved name ("dark"/"light")."""
    global _current_name
    if setting is None:
        import config

        setting = config.SETTINGS.get("theme", "dark")
    _current_name = resolve_theme(setting)
    app.setStyleSheet(build_stylesheet(THEMES[_current_name]))
    for cb in list(_listeners):
        try:
            cb(_current_name)
        except RuntimeError:
            _listeners.remove(cb)
    return _current_name


def watch_system_theme(app) -> None:
    """Re-apply when the OS colour scheme changes (only if theme == system)."""
    try:
        import config

        def _changed(*_a):
            if config.SETTINGS.get("theme") == "system":
                apply_theme(app, "system")

        app.styleHints().colorSchemeChanged.connect(_changed)
    except Exception:
        pass
