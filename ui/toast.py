"""Animated, stackable toast notifications.

A toast has a *title* (the section, e.g. "Modelo") and a *description* (the
change, e.g. "Se seleccionó Qwen3 4B"). Toasts slide in from the right while
fading, stack from the bottom-right corner, auto-dismiss, and can be closed by
clicking them. ``reduce_motion`` disables slide/fade animation.
"""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QParallelAnimationGroup, QPoint, QPropertyAnimation, QTimer, Qt
from PySide6.QtWidgets import QGraphicsOpacityEffect, QLabel, QVBoxLayout, QWidget

from ui import theme

_MARGIN = 20
_GAP = 8
_SLIDE_PX = 40


class Toast(QWidget):
    """A single toast; a child widget of the window it is anchored to."""

    def __init__(self, message: str, level: str = "info", parent=None,
                 lifetime_ms: int = 5000, title: str = "",
                 reduce_motion: bool = False, on_closed=None):
        super().__init__(parent)
        self.level = level
        self.title_text = title
        self.reduce_motion = reduce_motion
        self._on_closed = on_closed
        self._closing = False
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName(f"{title}: {message}" if title else message)
        self.setObjectName("toast")

        t = theme.tokens()
        accent = {"info": t["primary"], "warning": t["warning"],
                  "error": t["error"], "success": t["success"]}.get(level, t["primary"])
        self.setStyleSheet(
            f"QWidget#toast {{ background-color: {t['surface']}; border: 1px solid {t['border']}; "
            f"border-left: 4px solid {accent}; border-radius: 8px; }}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(2)

        self.title_label = QLabel(title)
        self.title_label.setStyleSheet(
            f"color: {accent}; font-size: 12px; font-weight: 700; background: transparent;"
        )
        self.title_label.setVisible(bool(title))
        layout.addWidget(self.title_label)

        self.label = QLabel(message)
        self.label.setWordWrap(True)
        self.label.setStyleSheet(
            f"color: {t['text']}; font-size: 13px; font-weight: 500; background: transparent;"
        )
        layout.addWidget(self.label)

        self.setFixedWidth(340)
        self.adjustSize()

        self._effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._effect)
        self._effect.setOpacity(0.0 if not reduce_motion else 1.0)
        if reduce_motion:
            self._effect.setOpacity(1.0)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.dismiss)
        self._timer.start(lifetime_ms)

        self._group: QParallelAnimationGroup | None = None
        self.target_pos = QPoint(0, 0)
        self.show()
        self.raise_()

    # -- placement / animation ------------------------------------------
    def move_to(self, pos: QPoint, animate: bool = True) -> None:
        first = not hasattr(self, "_placed")
        self._placed = True
        self.target_pos = pos
        if self.reduce_motion or not animate:
            self.move(pos)
            self._effect.setOpacity(1.0)
            return
        if first:
            self.move(pos + QPoint(_SLIDE_PX, 0))
            self._animate(self.pos(), pos, 0.0, 1.0, 240)
        else:
            self._animate(self.pos(), pos, self._effect.opacity(), 1.0, 160)

    def _animate(self, p0: QPoint, p1: QPoint, o0: float, o1: float, ms: int) -> None:
        if self._group is not None:
            self._group.stop()
        group = QParallelAnimationGroup(self)
        slide = QPropertyAnimation(self, b"pos", group)
        slide.setStartValue(p0)
        slide.setEndValue(p1)
        slide.setDuration(ms)
        slide.setEasingCurve(QEasingCurve.Type.OutCubic)
        fade = QPropertyAnimation(self._effect, b"opacity", group)
        fade.setStartValue(o0)
        fade.setEndValue(o1)
        fade.setDuration(ms)
        group.addAnimation(slide)
        group.addAnimation(fade)
        self._group = group
        group.start()

    def dismiss(self) -> None:
        if self._closing:
            return
        self._closing = True
        self._timer.stop()
        if self.reduce_motion:
            self._finish()
            return
        self._animate(self.pos(), self.pos() + QPoint(_SLIDE_PX, 0),
                      self._effect.opacity(), 0.0, 200)
        assert self._group is not None
        self._group.finished.connect(self._finish)

    def _finish(self) -> None:
        self.hide()
        if self._on_closed:
            self._on_closed(self)
        self.deleteLater()

    def mousePressEvent(self, event) -> None:  # click to close
        self.dismiss()
        event.accept()


class ToastManager:
    """Manages stacked toasts anchored to a parent widget (one per window)."""

    def __init__(self, parent_widget, reduce_motion: bool | None = None):
        self.parent = parent_widget
        self._toasts: list[Toast] = []
        self._reduce_motion = reduce_motion

    @property
    def reduce_motion(self) -> bool:
        if self._reduce_motion is not None:
            return self._reduce_motion
        try:
            import config
            return bool(config.SETTINGS.get("reduce_motion", False))
        except Exception:
            return False

    def show(self, message: str, level: str = "info", lifetime_ms: int = 5000,
             title: str = "") -> Toast:
        toast = Toast(message, level=level, parent=self.parent, lifetime_ms=lifetime_ms,
                      title=title, reduce_motion=self.reduce_motion,
                      on_closed=self._remove)
        self._toasts.append(toast)
        self._layout()
        return toast

    def info(self, message: str, lifetime_ms: int = 5000, title: str = "") -> Toast:
        return self.show(message, "info", lifetime_ms, title)

    def warning(self, message: str, lifetime_ms: int = 6000, title: str = "") -> Toast:
        return self.show(message, "warning", lifetime_ms, title)

    def error(self, message: str, lifetime_ms: int = 8000, title: str = "") -> Toast:
        return self.show(message, "error", lifetime_ms, title)

    def success(self, message: str, lifetime_ms: int = 4000, title: str = "") -> Toast:
        return self.show(message, "success", lifetime_ms, title)

    def _remove(self, toast: Toast) -> None:
        if toast in self._toasts:
            self._toasts.remove(toast)
        self._layout()

    def _layout(self) -> None:
        """Stack toasts from the bottom-right corner, newest at the bottom."""
        p = self.parent
        y = p.height() - _MARGIN
        for toast in reversed(self._toasts):
            if toast._closing:
                continue
            toast.adjustSize()
            y -= toast.height()
            x = p.width() - toast.width() - _MARGIN
            toast.move_to(QPoint(x, y))
            toast.raise_()
            y -= _GAP
