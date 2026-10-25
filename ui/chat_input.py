"""Chat input with inline ``@file``, ``/command`` and ``;tool`` autocomplete.

The widget owns a small non-focus-stealing :class:`QListWidget` popup that is a
child of the surrounding window.  Key handling is *not* done in
``keyPressEvent``: the main window's event filter calls
:meth:`ChatInput.handle_completion_key` first so that Enter still reaches the
Enter-to-send filter when no completion is visible.
"""

from __future__ import annotations

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt, Signal
from PySide6.QtGui import QImage, QKeyEvent, QTextCursor
from PySide6.QtWidgets import QListWidget, QTextEdit

from ui.completion_popup import CompletionItem, CompletionPopup, filter_items

_MAX_ROWS = 10
_POPUP_WIDTH = 420
_POPUP_MAX_HEIGHT = 220
_ROW_HEIGHT = 26
# Minimum composer height (about one and a half lines of text).
_MIN_HEIGHT = 52

_TRIGGERS = {"@", "/", ";"}

class ChatInput(QTextEdit):
    """A ``QTextEdit`` that offers completions for three trigger characters."""

    filesRequested = Signal()
    toolsRequested = Signal()
    heightChanged = Signal(int)      # composer auto-height, in pixels
    expandedChanged = Signal(bool)   # text no longer fits on one compact line
    imagePasted = Signal(bytes)      # PNG bytes from the clipboard
    filesDropped = Signal(list)      # local file paths (paste or drag & drop)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        self._file_candidates: list[str] = []
        self._skill_candidates: list[tuple[str, str]] = []
        self._command_candidates: list[tuple[str, str]] = []
        self._tool_candidates: list[tuple[str, str]] = []
        self._tools_loaded = False
        self._tool_empty_message = ""
        self._command_icon = None
        self._skill_icon = None
        self._tool_icon = None

        self._popup: QListWidget | None = None
        # ``(token_start, token)`` of the last "please send candidates" signal.
        self._requested_token: tuple[int, str] | None = None
        self._suppress_refresh = False

        # Height follows the content, clamped to the window-provided limits.
        self._min_height = _MIN_HEIGHT
        self._max_height = _MIN_HEIGHT
        self._resizing_height = False
        # Compact = single-line row (attach | field | send). Expanded = the
        # field becomes a floating panel and the buttons move below it.
        self._compact_width = 0
        self._expanded = False

        self.textChanged.connect(self._refresh)
        self.textChanged.connect(self._update_height)
        self.textChanged.connect(self._update_expansion)
        self.cursorPositionChanged.connect(self._refresh)
        self.document().documentLayout().documentSizeChanged.connect(self._update_height)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    # ── Paste / drop of images and files ────────────────────────────────

    def canInsertFromMimeData(self, source) -> bool:  # noqa: N802 (Qt API)
        return source.hasImage() or source.hasUrls() or super().canInsertFromMimeData(source)

    def insertFromMimeData(self, source) -> None:  # noqa: N802 (Qt API)
        paths = [u.toLocalFile() for u in source.urls() if u.isLocalFile()] if source.hasUrls() else []
        if paths:
            self.filesDropped.emit(paths)
            return
        if source.hasImage():
            image = source.imageData()
            if isinstance(image, QImage) and not image.isNull():
                buf = QBuffer()
                buf.open(QIODevice.OpenModeFlag.WriteOnly)
                image.save(buf, "PNG")
                self.imagePasted.emit(bytes(QByteArray(buf.data())))
                return
        super().insertFromMimeData(source)

    # ── Candidate setters ────────────────────────────────────────────────

    def set_file_candidates(self, paths: list[str]) -> None:
        self._file_candidates = list(paths)
        self._refresh()

    def set_command_candidates(self, commands: list[tuple[str, str]]) -> None:
        self._command_candidates = list(commands)
        self._refresh()

    def set_skill_candidates(self, skills: list[tuple[str, str]]) -> None:
        """``(skill_id, description)`` pairs offered after ``@``."""
        self._skill_candidates = list(skills)
        self._refresh()

    def set_tool_candidates(self, tools: list[tuple[str, str]],
                            empty_message: str = "") -> None:
        self._tool_candidates = list(tools)
        self._tools_loaded = True
        self._tool_empty_message = empty_message
        self._refresh()

    def set_icons(self, command=None, skill=None, tool=None) -> None:
        self._command_icon, self._skill_icon, self._tool_icon = command, skill, tool

    # ── Compact / expanded composer ──────────────────────────────────────

    def set_compact_width(self, width: int) -> None:
        """Width the field has in the single-line layout, in pixels."""
        width = max(80, int(width))
        if width == self._compact_width:
            return
        self._compact_width = width
        self._update_expansion()

    def is_expanded(self) -> bool:
        return self._expanded

    def _update_expansion(self, *_args) -> None:
        text = self.toPlainText()
        if self._compact_width:
            # Compare against the *compact* width (not the current one) so the
            # field does not flip back and forth once it is already expanded.
            available = self._compact_width - 24
            expanded = "\n" in text or self.fontMetrics().horizontalAdvance(text) > available
        else:
            expanded = "\n" in text
        if expanded != self._expanded:
            self._expanded = expanded
            self.expandedChanged.emit(expanded)

    # ── Auto-growing height ──────────────────────────────────────────────

    def set_height_limits(self, minimum: int, maximum: int) -> None:
        """Clamp the auto height; ``maximum`` is usually 50% of the viewport."""
        self._min_height = max(1, int(minimum))
        self._max_height = max(self._min_height, int(maximum))
        self._update_height()

    def _update_height(self, *_args) -> None:
        if getattr(self, "_resizing_height", False):
            return
        # ``contentsRect().top()`` is the stylesheet border + vertical padding,
        # which the document size does not include.
        chrome = 2 * self.contentsRect().top()
        desired = int(round(self.document().size().height())) + chrome
        desired = max(self._min_height, min(self._max_height, desired))
        if desired == self.height():
            return
        self._resizing_height = True
        try:
            self.setFixedHeight(desired)
        finally:
            self._resizing_height = False
        self.heightChanged.emit(desired)

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt API)
        super().resizeEvent(event)
        # While compact, the current width *is* the compact width.
        if not getattr(self, "_expanded", False) and self.width() > 0:
            self._compact_width = self.width()
        # Re-wrapping can change the document height at a new width.
        if hasattr(self, "_min_height"):
            self._update_height()

    # ── Popup lifecycle ──────────────────────────────────────────────────

    def hide_completion(self) -> None:
        if self._popup is not None:
            self._popup.hide()

    def _ensure_popup(self) -> CompletionPopup:
        window = self.window()
        if self._popup is None:
            self._popup = CompletionPopup(window)
        elif self._popup.parentWidget() is not window:
            self._popup.setParent(window)
        return self._popup

    def _position_popup(self, row_count: int) -> None:
        popup = self._popup
        if popup is None:
            return

        window = self.window()
        cursor_rect = self.cursorRect()
        point = self.viewport().mapTo(window, cursor_rect.bottomLeft())

        height = min(_POPUP_MAX_HEIGHT, 8 + row_count * _ROW_HEIGHT)
        popup.setFixedWidth(_POPUP_WIDTH)
        popup.setMaximumHeight(_POPUP_MAX_HEIGHT)
        popup.resize(_POPUP_WIDTH, height)

        x = max(0, min(point.x(), max(0, window.width() - _POPUP_WIDTH)))
        y = point.y() + 2
        y = min(y, max(0, window.height() - height))
        popup.move(x, y)

    # ── Token detection and refresh ──────────────────────────────────────

    def _detect_token(self) -> tuple[str, int, str, str] | None:
        """Return ``(trigger, start, token, query)`` for the token at the cursor."""
        cursor = self.textCursor()
        if cursor.hasSelection():
            return None

        position = cursor.position()
        text = self.toPlainText()
        if position <= 0 or position > len(text):
            return None

        start = position
        while start > 0 and not text[start - 1].isspace():
            start -= 1

        token = text[start:position]
        if not token or token[0] not in _TRIGGERS:
            return None
        if start > 0 and not text[start - 1].isspace():
            return None

        return token[0], start, token, token[1:]

    def _candidate_count(self, trigger: str) -> int:
        if trigger == "@":
            return len(self._file_candidates) + len(self._skill_candidates)
        if trigger == "/":
            return len(self._command_candidates)
        if self._tools_loaded and self._tool_empty_message:
            return 1
        return len(self._tool_candidates)

    def _matching_items(self, trigger: str, query: str) -> list[CompletionItem]:
        items: list[CompletionItem] = []
        if trigger == "@":
            for sid, desc in self._skill_candidates:
                sid = sid.removeprefix("@")
                items.append(CompletionItem(f"@{sid}", f"@{sid}", desc, "skill", self._skill_icon))
            for raw_path in self._file_candidates:
                path = raw_path.removeprefix("@")
                completion = f'@"{path}"' if any(c.isspace() for c in path) else f"@{path}"
                items.append(CompletionItem(f"@{path}", completion, "", "file"))
        elif trigger == "/":
            for raw_name, desc in self._command_candidates:
                name = raw_name.removeprefix("/")
                items.append(CompletionItem(f"/{name}", f"/{name}", desc, "cmd", self._command_icon))
        else:
            if not self._tool_candidates and self._tools_loaded and self._tool_empty_message:
                return [CompletionItem(self._tool_empty_message, "", "", "MCP", enabled=False)]
            for raw, desc in self._tool_candidates:
                mention = raw.removeprefix(";")
                items.append(CompletionItem(f";{mention}", f";{mention}", desc, "MCP", self._tool_icon))
        return filter_items(items, query, _MAX_ROWS)

    def _refresh(self) -> None:
        if self._suppress_refresh:
            return

        detected = self._detect_token()
        if detected is None:
            self._requested_token = None
            self.hide_completion()
            return

        trigger, start, token, query = detected
        if self._candidate_count(trigger) == 0:
            self.hide_completion()
            self._maybe_request(trigger, start, token)
            return

        rows = self._matching_items(trigger, query)
        if not rows:
            self.hide_completion()
            return

        popup = self._ensure_popup()
        popup.set_items(rows)
        self._position_popup(len(rows))
        popup.raise_()
        popup.show()

    def _maybe_request(self, trigger: str, start: int, token: str) -> None:
        """Ask the window for candidates once per trigger occurrence."""
        if self._requested_token is not None:
            last_start, last_token = self._requested_token
            if last_start == start and token.startswith(last_token):
                return

        self._requested_token = (start, token)
        if trigger == "@":
            self.filesRequested.emit()
        elif trigger == ";" and not self._tools_loaded:
            self.toolsRequested.emit()

    # ── Key handling ─────────────────────────────────────────────────────

    def handle_completion_key(self, event: QKeyEvent) -> bool:
        """Consume a completion key; return ``True`` only if it was used."""
        popup = self._popup
        visible = popup is not None and not popup.isHidden()
        if not visible:
            return False

        key = event.key()

        if key in (Qt.Key.Key_Down, Qt.Key.Key_Up):
            if popup.count() == 0:
                return False
            popup.move_selection(1 if key == Qt.Key.Key_Down else -1)
            return True

        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Tab):
            if popup.current_completion() is None:
                return False
            self._accept_current()
            return True

        if key == Qt.Key.Key_Escape:
            self.hide_completion()
            return True

        return False

    def _accept_current(self) -> None:
        popup = self._popup
        if popup is None:
            return
        completion = popup.current_completion()
        detected = self._detect_token()
        if not completion or detected is None:
            self.hide_completion()
            return

        _trigger, start, _token, _query = detected
        end = self.textCursor().position()

        cursor = self.textCursor()
        self._suppress_refresh = True
        try:
            cursor.setPosition(start)
            cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
            cursor.insertText(f"{completion} ")
            self.setTextCursor(cursor)
        finally:
            self._suppress_refresh = False

        self.hide_completion()
        self.setFocus(Qt.FocusReason.OtherFocusReason)
