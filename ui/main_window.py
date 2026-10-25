import html
import threading
import markdown
from PySide6.QtCore import QThread, QTimer, QUrl, Qt, Signal, QPoint, QEvent
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QTextBrowser, QTextEdit,
    QPushButton, QLabel, QComboBox, QDockWidget, QFileDialog, QMenuBar, QApplication,
    QSizePolicy,
)

import config
from core import memory
from core.ai_engine import AIEngine
from core.providers.base_provider import RequestCancelled
from core import attachments as attachments_mod
from core import skills_manager
from core.providers.capabilities import get_capabilities
from ui.icons import get_icon
from ui.dev_console import DevConsole
from ui.hardware_widget import HardwareWidget
from ui.settings_dialog import SettingsDialog
from ui.skills_dialog import SkillsDialog
from ui.chat_history_widget import ChatHistoryWidget
from ui.toast import ToastManager
from ui.attachment_tray import AttachmentTray
from ui.chat_input import ChatInput
from ui.commands import command_pairs
from ui import theme
from ui.theme import FONT_UI as _FONT_UI


def _rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r}, {g}, {b}, {alpha})"


# One and a half lines of text: the composer's resting height.
_COMPOSER_MIN_HEIGHT = 52
# The expanded panel starts at about three lines and grows up to 50% of the app.
_COMPOSER_EXPANDED_MIN_HEIGHT = 90


class AIWorker(QThread):
    response_ready = Signal(str, str)   # (chat_id, text)
    error_occurred = Signal(str, str)   # (chat_id, error message)

    def __init__(self, ai_engine, chat_id, prompt, attachments=None):
        super().__init__()
        self.ai_engine = ai_engine
        self.chat_id = chat_id
        self.prompt = prompt
        self.attachments = attachments or []
        self.cancel_event = threading.Event()

    @property
    def was_cancelled(self) -> bool:
        return self.cancel_event.is_set()

    def cancel(self):
        """Ask the agent loop to stop. It stops at the next step boundary."""
        self.cancel_event.set()

    def run(self):
        try:
            result = self.ai_engine.process_message(
                self.prompt,
                cancel_event=self.cancel_event,
                chat_id=self.chat_id,
                attachments=self.attachments or None,
            )
            if not self.was_cancelled:
                self.response_ready.emit(self.chat_id, result)
        except RequestCancelled:
            pass  # the UI is restored by MainWindow._on_worker_finished
        except Exception as e:
            if not self.was_cancelled:
                self.error_occurred.emit(self.chat_id, str(e))


class TitleWorker(QThread):
    title_generated = Signal(str, str)  # (chat_id, new_title)

    def __init__(self, ai_engine: AIEngine, chat_id: str, first_message: str):
        super().__init__()
        self.ai_engine = ai_engine
        self.chat_id = chat_id
        self.first_message = first_message
        self.cancel_event = threading.Event()

    def cancel(self):
        self.cancel_event.set()

    def run(self):
        try:
            prompt = (
                f"Generate a short title (3 to 5 words max) for a chat that starts with: "
                f"'{self.first_message}'. Output ONLY the title text, without quotes or punctuation."
            )
            # save_to_memory=False: the title prompt must not end up in the chat history
            # use_history=False: don't pull another chat's history into the title request
            title = self.ai_engine.process_message(
                prompt,
                save_to_memory=False,
                cancel_event=self.cancel_event,
                use_history=False,
                chat_id=self.chat_id,
                purpose="title",
            ).strip()
            clean_title = "".join(c for c in title if c.isalnum() or c in (" ", "_", "-")).strip()
            clean_title = clean_title.replace(" ", "_")
            if clean_title:
                self.title_generated.emit(self.chat_id, clean_title[:35])
        except Exception:
            pass


class MCPConnectWorker(QThread):
    """Connect MCP servers off the GUI thread (stdio servers start subprocesses)."""

    done = Signal(list)

    def __init__(self, ai_engine):
        super().__init__()
        self.ai_engine = ai_engine

    def run(self):
        try:
            self.done.emit(list(self.ai_engine.connect_mcp()))
        except Exception as exc:
            self.ai_engine.logger.log("error", {"message": f"MCP connect failed: {exc}"})
            self.done.emit([])


class ReasoningSpinner(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        self.label = QLabel("Thinking and running actions")
        self.label.setProperty("muted", True)
        self.label.setStyleSheet("font-style: italic; font-size: 13px;")
        layout.addWidget(self.label)
        self.setLayout(layout)
        self.dots = 0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._animate)

    def _animate(self):
        self.dots = (self.dots + 1) % 4
        self.label.setText("Thinking and running actions" + "." * self.dots)

    def start(self):
        self.dots = 0
        self.timer.start(400)
        self.show()

    def stop(self):
        self.timer.stop()
        self.hide()


class MainWindow(QMainWindow):
    def __init__(self, chat_id: str = "main_project"):
        super().__init__()
        self.chat_id = chat_id
        self.ai_engine = AIEngine(chat_id=self.chat_id)
        self.worker: AIWorker | None = None
        self._title_workers: set[TitleWorker] = set()
        self._pending_titles: dict[str, str] = {}
        self.toast_manager = ToastManager(self)
        self._mcp_worker: MCPConnectWorker | None = None
        self._mcp_loaded = False

        # Check if chat is brand new
        existing_messages = memory.load_chat(self.chat_id)
        self.is_first_message = len(existing_messages) == 0

        self._init_ui()
        self._load_chat_history()
        self.ai_engine.logger.event_logged.connect(self._on_engine_event)
        self._refresh_completion_sources()
        theme.on_theme_changed(self._on_theme_changed)
        QTimer.singleShot(0, self._start_mcp_connect)

    def _init_ui(self):
        self._update_window_title()
        self.resize(1000, 700)
        self._build_menu()

        # Layout:
        #   [history] [conversation + floating composer] [hardware]
        #   [history] [conversation                   ] [dev console, if active]
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 12, 16, 16)

        # Top bar
        top_bar = QHBoxLayout()
        top_bar.setSpacing(8)
        status_label = QLabel("Active model:")
        status_label.setStyleSheet("font-weight: 600; font-size: 13px;")

        self.provider_combo = QComboBox()
        self._populate_provider_combo()
        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)

        top_bar.addWidget(status_label)
        top_bar.addWidget(self.provider_combo)
        top_bar.addStretch()
        layout.addLayout(top_bar)

        # Chat view fills the whole area; the composer floats on top of its
        # bottom edge so growing text never squeezes the conversation.
        self.chat_display = QTextBrowser()
        self.chat_display.setOpenExternalLinks(True)
        self.chat_display.setAccessibleName("Conversation")
        self.chat_display.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        chat_area = QGridLayout()
        chat_area.setContentsMargins(0, 0, 0, 0)
        chat_area.setSpacing(0)
        chat_area.addWidget(self.chat_display, 0, 0)
        chat_area.setRowStretch(0, 1)

        # Composer: a floating card anchored to the bottom of the chat column.
        self.composer = QWidget()
        self.composer.setObjectName("composer")
        self.composer.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.composer.installEventFilter(self)
        composer_layout = QVBoxLayout(self.composer)
        composer_layout.setContentsMargins(12, 10, 12, 10)
        composer_layout.setSpacing(6)

        self.spinner = ReasoningSpinner()
        self.spinner.hide()
        composer_layout.addWidget(self.spinner)

        self.tray = AttachmentTray(lambda: self.chat_id)
        self.tray.rejected.connect(lambda msg: self.toast_manager.warning(msg, title="Adjuntos"))
        composer_layout.addWidget(self.tray)

        self.input_grid = QGridLayout()
        self.input_grid.setSpacing(8)
        self.attach_button = QPushButton()
        self.attach_button.setIcon(get_icon("upload"))
        self.attach_button.setToolTip("Attach images or files (or paste / drag & drop)")
        self.attach_button.setAccessibleName("Attach files")
        self.attach_button.setProperty("secondary", True)
        self.attach_button.clicked.connect(self._attach_file)

        self.input_field = ChatInput()
        self.input_field.setPlaceholderText("Type an instruction or question...")
        self.input_field.setAccessibleName("Message")
        self.input_field.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.input_field.installEventFilter(self)
        self._apply_input_icons()
        self.input_field.imagePasted.connect(self._on_image_pasted)
        self.input_field.filesDropped.connect(self._on_files_dropped)
        self.input_field.filesRequested.connect(self._provide_file_candidates)
        self.input_field.toolsRequested.connect(self._provide_tool_candidates)
        self.input_field.heightChanged.connect(self._on_composer_height_changed)
        self.input_field.expandedChanged.connect(self._on_input_expanded)

        self.send_button = QPushButton("Send")
        self.send_button.setIcon(get_icon("send"))
        self.send_button.setAccessibleName("Send message")
        self.send_button.clicked.connect(self._send_message)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setIcon(get_icon("stop"))
        self.cancel_button.setProperty("danger", True)
        self.cancel_button.clicked.connect(self._cancel_request)
        self.cancel_button.hide()

        # Buttons keep their natural width and stay pinned to the bottom edge,
        # however tall the text field becomes.
        for button in (self.attach_button, self.send_button, self.cancel_button):
            button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        self.hint_label = QLabel("/ comandos · @ skills · ; MCP")
        self.hint_label.setProperty("muted", True)
        self.hint_label.setStyleSheet("font-size: 11px;")

        self._apply_composer_layout(expanded=False)
        composer_layout.addLayout(self.input_grid)
        composer_layout.addWidget(self.hint_label)

        # Same cell as the chat, bottom-aligned: the composer floats above it.
        chat_area.addWidget(self.composer, 0, 0, Qt.AlignmentFlag.AlignBottom)
        layout.addLayout(chat_area, 1)

        self.setCentralWidget(container)

        self._update_composer_limits()
        self._build_docks()
        self._apply_dev_mode_visibility()
        self._update_chat_clearance()

    def _apply_composer_layout(self, expanded: bool):
        """Compact row: [attach][field][send]. Expanded: field panel + buttons below."""
        grid = self.input_grid
        for widget in (self.attach_button, self.input_field,
                       self.send_button, self.cancel_button):
            grid.removeWidget(widget)

        if expanded:
            grid.addWidget(self.input_field, 0, 0, 1, 3)
            grid.addWidget(self.attach_button, 1, 0, Qt.AlignmentFlag.AlignLeft)
            grid.addWidget(self.send_button, 1, 2, Qt.AlignmentFlag.AlignRight)
            grid.addWidget(self.cancel_button, 1, 2, Qt.AlignmentFlag.AlignRight)
        else:
            grid.addWidget(self.attach_button, 0, 0, Qt.AlignmentFlag.AlignBottom)
            grid.addWidget(self.input_field, 0, 1)
            grid.addWidget(self.send_button, 0, 2,
                           Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight)
            grid.addWidget(self.cancel_button, 0, 2,
                           Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight)
        grid.setColumnStretch(1, 1)

    def _on_input_expanded(self, expanded: bool):
        self._apply_composer_layout(expanded)
        self._update_composer_limits()
        self._schedule_right_column_sync()

    def _update_compact_width(self):
        """Tell the field how wide it is in the single-line layout."""
        if not hasattr(self, "input_grid") or not hasattr(self, "input_field"):
            return
        margins = self.composer.layout().contentsMargins()
        right_width = max(self.send_button.sizeHint().width(),
                          self.cancel_button.sizeHint().width())
        compact = (self.composer.width() - margins.left() - margins.right()
                   - self.attach_button.sizeHint().width() - right_width
                   - 2 * self.input_grid.spacing())
        self.input_field.set_compact_width(compact)

    def _update_chat_clearance(self):
        """Keep the end of the conversation readable above the floating card."""
        self.chat_display.setViewportMargins(0, 0, 0, self.composer.height() + 8)

    def _update_composer_limits(self):
        """The composer may grow up to half of the window height."""
        if not hasattr(self, "input_field"):
            return
        minimum = (_COMPOSER_EXPANDED_MIN_HEIGHT if self.input_field.is_expanded()
                   else _COMPOSER_MIN_HEIGHT)
        max_height = max(minimum, int(self.height() * 0.5))
        self.input_field.set_height_limits(minimum, max_height)

    def resizeEvent(self, event):  # noqa: N802 (Qt API)
        super().resizeEvent(event)
        self._update_composer_limits()
        self._schedule_right_column_sync()

    def _build_menu(self):
        menu_bar: QMenuBar = self.menuBar()

        settings_menu = menu_bar.addMenu("Settings")
        open_settings_action = settings_menu.addAction(get_icon("settings"), "Preferences...")
        open_settings_action.triggered.connect(self._open_settings)

        skills_menu = menu_bar.addMenu("Skills")
        open_skills_action = skills_menu.addAction(get_icon("puzzle"), "Manage skills...")
        open_skills_action.triggered.connect(self._open_skills)

        view_menu = menu_bar.addMenu("View")
        self.toggle_history_action = view_menu.addAction(get_icon("chat"), "Chat History panel")
        self.toggle_history_action.setCheckable(True)
        self.toggle_history_action.setChecked(True)
        self.toggle_history_action.triggered.connect(lambda c: self.history_dock.setVisible(c))

        self.toggle_dev_action = view_menu.addAction(get_icon("bug"), "Dev Mode panel")
        self.toggle_dev_action.setCheckable(True)
        self.toggle_dev_action.setChecked(config.SETTINGS.get("dev_mode", False))
        self.toggle_dev_action.triggered.connect(self._toggle_dev_mode)

        self.toggle_hw_action = view_menu.addAction(get_icon("chart"), "Hardware Monitor panel")
        self.toggle_hw_action.setCheckable(True)
        self.toggle_hw_action.setChecked(True)
        self.toggle_hw_action.triggered.connect(self._toggle_hardware_panel)

        help_menu = menu_bar.addMenu("Help")
        help_action = help_menu.addAction(get_icon("help"), "Commands")
        help_action.triggered.connect(self._show_help)

    def _build_docks(self):
        # Left Dock: History Panel
        self.history_dock = QDockWidget("Chats", self)
        self.history_widget = ChatHistoryWidget(self.chat_id)
        self.history_widget.chat_selected.connect(self._on_chat_selected)
        self.history_dock.setWidget(self.history_widget)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.history_dock)

        # Right Dock: Hardware Monitor (top rows) then Dev Console (last row)
        self.hw_dock = QDockWidget("Hardware Monitor", self)
        self.hardware_widget = HardwareWidget()
        self.hw_dock.setWidget(self.hardware_widget)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.hw_dock)

        self.dev_dock = QDockWidget("Dev Mode", self)
        self.dev_console = DevConsole(self.ai_engine.logger)
        self.dev_dock.setWidget(self.dev_console)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dev_dock)
        self.splitDockWidget(self.hw_dock, self.dev_dock, Qt.Orientation.Vertical)

    def _load_chat_history(self):
        """Loads and displays existing chat history from memory storage."""
        self.chat_display.clear()
        messages = memory.load_chat(self.chat_id)

        if messages:
            for msg in messages:
                role = msg.get("role", "assistant")
                sender = "You" if role == "user" else "Assistant" if role == "assistant" else "System"
                self._add_message(sender, msg.get("content", ""), msg.get("attachments"))
        else:
            self._add_message("Assistant", f"Ready. Active model: **{self.ai_engine.config_label()}**.")

    def _on_chat_selected(self, new_chat_id: str):
        self.chat_id = new_chat_id
        self.tray.clear_discard()
        self._update_window_title()
        self.ai_engine.switch_chat(new_chat_id)   # was: self.ai_engine = AIEngine(...)
        existing_messages = memory.load_chat(self.chat_id)
        self.is_first_message = len(existing_messages) == 0
        self._load_chat_history()

    def eventFilter(self, obj, event):
        if obj is self.composer and event.type() == QEvent.Type.Resize:
            self._update_compact_width()
            self._update_chat_clearance()
        if obj is getattr(self, "input_field", None) and event.type() == QEvent.Type.KeyPress:
            if self.input_field.handle_completion_key(event):
                return True
            key = event.key()
            modifiers = event.modifiers()
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if modifiers & Qt.KeyboardModifier.ShiftModifier:
                    return False  # let Shift+Enter insert a newline
                self._send_message()
                return True
        return super().eventFilter(obj, event)

    # ── Completion sources ───────────────────────────────────────────────
    def _apply_input_icons(self):
        t = theme.tokens()
        self.input_field.set_icons(
            command=get_icon("terminal", t["muted"], 16),
            skill=get_icon("puzzle", t["muted"], 16),
            tool=get_icon("settings", t["muted"], 16),
        )

    def _refresh_completion_sources(self):
        self.input_field.set_command_candidates(command_pairs())
        self.input_field.set_skill_candidates(
            [(s.id, s.description) for s in skills_manager.enabled_skills()]
        )
        self._provide_tool_candidates()

    def _provide_file_candidates(self):
        """Workspace files for ``@`` (relative paths, capped)."""
        root = config.WORKSPACE_DIR if hasattr(config, "WORKSPACE_DIR") else config.BASE_DIR
        files: list[str] = []
        try:
            for p in sorted(root.rglob("*")):
                if p.is_file() and not any(part.startswith(".") for part in p.parts):
                    files.append(p.relative_to(root).as_posix())
                if len(files) >= 200:
                    break
        except OSError:
            pass
        self.input_field.set_file_candidates(files)

    def _provide_tool_candidates(self):
        manager = self.ai_engine.mcp_manager
        tools = [(t.mention, t.description[:80]) for t in manager.list_tools()]
        if tools:
            self.input_field.set_tool_candidates(tools)
        elif self._mcp_loaded:
            self.input_field.set_tool_candidates([], "No hay servidores MCP configurados")

    # ── MCP ──────────────────────────────────────────────────────────────
    def _start_mcp_connect(self):
        if self._mcp_worker is not None and self._mcp_worker.isRunning():
            return
        self._mcp_worker = MCPConnectWorker(self.ai_engine)
        self._mcp_worker.done.connect(self._on_mcp_connected)
        self._mcp_worker.start()

    def _on_mcp_connected(self, statuses: list):
        self._mcp_loaded = True
        self._provide_tool_candidates()
        failed = [st for st in statuses if st.enabled and not st.connected]
        if failed:
            self.toast_manager.warning(
                f"{failed[0].label}: {failed[0].error or 'sin conexión'}", title="MCP")

    def _mcp_summary(self) -> str:
        statuses = self.ai_engine.mcp_manager.status()
        if not statuses:
            return "No hay servidores MCP configurados. Añade uno en Settings → MCP."
        lines = ["**MCP servers:**"]
        for st in statuses:
            lines.append(f"- `{st.server_id}` ({st.transport}): {st.summary()}")
        tools = self.ai_engine.mcp_manager.list_tools()
        if tools:
            lines.append("\n**Tools** (use `;server.tool`):")
            lines.extend(f"- `;{t.mention}` — {t.description[:80]}" for t in tools)
        return "\n".join(lines)

    # ── Engine events → toasts ───────────────────────────────────────────
    def _on_engine_event(self, event: dict):
        kind = event.get("type")
        payload = event.get("payload", {})
        if kind == "tool_effect":
            self.toast_manager.success(payload.get("description", ""), title=payload.get("title", ""))
        elif kind == "attachments_skipped":
            self.toast_manager.warning(
                "El modelo activo no admite imágenes: solo se envió la lista de adjuntos.",
                title="Adjuntos")

    # ── Theme ────────────────────────────────────────────────────────────
    def _on_theme_changed(self, _name: str):
        try:
            self._apply_input_icons()
            self._load_chat_history()
        except RuntimeError:
            pass  # window already destroyed

    def _apply_theme_from_settings(self):
        theme.apply_theme(QApplication.instance())

    def _send_message(self):
        text = self.input_field.toPlainText().strip()
        if not text and not self.tray.items:
            return

        if text.startswith("/") and not self.tray.items and self._process_slash_command(text):
            self.input_field.clear()
            return
        if not text:
            text = "Describe the attachments."

        attachments = self.tray.take()
        self._add_message("You", text, attachments)
        self.input_field.clear()
        self.input_field.hide_completion()

        self.send_button.hide()
        self.cancel_button.show()
        self.input_field.setEnabled(False)
        self.spinner.start()

        # Defer the automatic title until the first response is in: generating it
        # in parallel raced the chat switch and dropped the response.
        if self.is_first_message:
            self._pending_titles[self.chat_id] = text
            self.is_first_message = False

        self.worker = AIWorker(self.ai_engine, self.chat_id, text)
        self.worker.attachments = attachments
        self.worker.response_ready.connect(self._receive_response)
        self.worker.error_occurred.connect(self._handle_error)
        self.worker.finished.connect(self._on_worker_finished)
        self.worker.start()

    def _generate_auto_title(self, first_message: str, chat_id: str):
        worker = TitleWorker(self.ai_engine, chat_id, first_message)
        worker.title_generated.connect(self._on_title_generated)
        # Keep every worker alive until it finishes: replacing a single
        # attribute would destroy a running QThread and abort the process.
        worker.finished.connect(lambda w=worker: self._title_workers.discard(w))
        worker.finished.connect(worker.deleteLater)
        self._title_workers.add(worker)
        worker.start()

    def _on_title_generated(self, chat_id: str, new_title: str):
        # The chat id is immutable; the title is metadata stored alongside it.
        if not memory.set_chat_title(chat_id, new_title):
            return
        if chat_id == self.chat_id:
            self._update_window_title(new_title)
        self.history_widget.refresh()

    def _update_window_title(self, title: str | None = None):
        if title is None:
            title = memory.get_chat_title(self.chat_id)
        if title:
            self.setWindowTitle(f"AI Desktop Assistant - {title} [{self.chat_id}]")
        else:
            self.setWindowTitle(f"AI Desktop Assistant - [{self.chat_id}]")

    def _receive_response(self, chat_id: str, response: str):
        self.spinner.stop()
        prompt = self._pending_titles.pop(chat_id, None)
        if prompt:
            self._generate_auto_title(prompt, chat_id)
        if chat_id == self.chat_id:
            self._add_message("Assistant", response)
            self.toast_manager.info(f"Respuesta entregada en {chat_id}", title="Chat")
        else:
            # The response landed in another chat (the user switched away while
            # it was running): keep it there and say so instead of dropping it.
            self.toast_manager.info(f"Respuesta guardada en {chat_id}", title="Chat")
            self.statusBar().showMessage(f"Response saved to chat '{chat_id}'.", 6000)
        self._reset_input_state()
        self.history_widget.refresh()

    def _handle_error(self, chat_id: str, error_message: str):
        self.spinner.stop()
        self._pending_titles.pop(chat_id, None)  # don't title a chat whose turn failed
        if chat_id == self.chat_id:
            self._add_message("System", f"**Error:** {error_message}")
            self.toast_manager.error(error_message, title="Error")
        else:
            self.toast_manager.error(f"{chat_id}: {error_message}", title="Error")
            self.statusBar().showMessage(f"Error in chat '{chat_id}': {error_message}", 6000)
        self._reset_input_state()

    def _cancel_request(self):
        """Ask the running worker to stop. Never blocks the UI thread: the UI is
        restored in _on_worker_finished once the thread has actually stopped."""
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.cancel_button.setEnabled(False)
            self.cancel_button.setText("Cancelling...")
        else:
            self._reset_input_state()

    def _on_worker_finished(self):
        """Runs on the GUI thread when the AIWorker thread ends (cancelled or not)."""
        if self.worker is not None and self.worker.was_cancelled:
            self._pending_titles.pop(self.worker.chat_id, None)
            self.spinner.stop()
            self._add_message("System", "*Request cancelled by user.*")
            self._reset_input_state()

    def _reset_input_state(self):
        self.cancel_button.hide()
        self.cancel_button.setEnabled(True)
        self.cancel_button.setText("Cancel")
        self.send_button.show()
        self.input_field.setEnabled(True)
        self.input_field.setFocus()

    def closeEvent(self, event):
        # Don't destroy a QThread that is still running (that aborts the app).
        workers = [w for w in [self.worker, *self._title_workers] if w is not None]
        for worker in workers:
            if worker.isRunning():
                worker.cancel()
        for worker in workers:
            if worker.isRunning():
                worker.wait(3000)
        if self._mcp_worker is not None and self._mcp_worker.isRunning():
            self._mcp_worker.wait(3000)
        try:
            self.ai_engine.close()
        except Exception:
            pass
        super().closeEvent(event)

    def _populate_provider_combo(self):
        self.provider_combo.blockSignals(True)
        self.provider_combo.clear()
        active_id = config.SETTINGS.get("active_provider")
        selected_index = 0
        for i, provider in enumerate(config.SETTINGS.get("providers", [])):
            icon_name = "cloud" if provider["type"] == "gemini" or "cloud" in provider["id"] else "cpu"
            self.provider_combo.addItem(get_icon(icon_name), provider["label"], provider["id"])
            if provider["id"] == active_id:
                selected_index = i
        self.provider_combo.setCurrentIndex(selected_index)
        self.provider_combo.blockSignals(False)

    def _on_provider_changed(self, index: int):
        if index < 0:
            return
        provider_id = self.provider_combo.itemData(index)
        settings = dict(config.SETTINGS)
        settings["active_provider"] = provider_id
        config.save_settings(settings)
        config.reload_settings()
        self.ai_engine.refresh_settings()
        self.toast_manager.info(f"Se seleccionó {self.ai_engine.config_label()}", title="Modelo")
        caps = get_capabilities(config.get_active_provider())
        if not caps.supports_vision:
            self.hint_label.setText("/ comandos · @ skills · ; MCP · este modelo no admite imágenes")
        else:
            self.hint_label.setText("/ comandos · @ skills · ; MCP")

    def _open_settings(self):
        dialog = SettingsDialog(self)
        if dialog.exec():
            self.ai_engine.refresh_settings()
            self._populate_provider_combo()
            self._apply_dev_mode_visibility()
            self._apply_theme_from_settings()
            self._start_mcp_connect()
            self._refresh_completion_sources()
            self.toast_manager.success("Se guardaron los cambios", title="Configuración")

    def _open_skills(self):
        dialog = SkillsDialog(self)
        if dialog.exec():
            self.ai_engine.refresh_settings()
            self._refresh_completion_sources()
            self.toast_manager.success("Se actualizaron las skills habilitadas", title="Skills")

    def _toggle_dev_mode(self, checked: bool):
        settings = dict(config.SETTINGS)
        settings["dev_mode"] = checked
        config.save_settings(settings)
        config.reload_settings()
        self._apply_dev_mode_visibility()

    def _toggle_hardware_panel(self, checked: bool):
        self.hw_dock.setVisible(checked)

    def _sync_right_column_split(self):
        """Keep the dev console in the composer row of the right column."""
        if not hasattr(self, "dev_dock") or not self.dev_dock.isVisible():
            return
        # Rows are measured from the composer top to the bottom of the window,
        # so the dev console grows together with the composer.
        available = self.height() - self.menuBar().sizeHint().height()
        composer_top = self.composer.mapTo(self, QPoint(0, 0)).y()
        composer_row = max(120, self.height() - composer_top)
        self.resizeDocks(
            [self.hw_dock, self.dev_dock],
            [max(160, available - composer_row), composer_row],
            Qt.Orientation.Vertical,
        )

    def _schedule_right_column_sync(self):
        """Debounce: typing resizes the composer on every keystroke."""
        if not hasattr(self, "_split_timer"):
            self._split_timer = QTimer(self)
            self._split_timer.setSingleShot(True)
            self._split_timer.timeout.connect(self._sync_right_column_split)
        self._split_timer.start(60)

    def _on_composer_height_changed(self, _height: int):
        # The dev console shares the last row with the composer.
        self._schedule_right_column_sync()

    def _apply_dev_mode_visibility(self):
        visible = config.SETTINGS.get("dev_mode", False)
        self.dev_dock.setVisible(visible)
        self.toggle_dev_action.setChecked(visible)
        if visible:
            QTimer.singleShot(0, self._sync_right_column_split)

    def _show_help(self):
        help_md = (
            "**Commands** (type `/`):\n"
            "- `/clear` clear the view · `/new` new chat · `/export` save chat as Markdown\n"
            "- `/model [name]` switch model · `/settings` · `/skills` · `/mcp` · `/dev` · `/help`\n\n"
            "**Mentions:**\n"
            "- `@skill-id` activate a skill for this message (also `@file` from the workspace)\n"
            "- `;server.tool` ask for an MCP tool; add `{json}` to pass exact arguments\n\n"
            "**Attachments:** paste (Ctrl+V), drag & drop or use the clip. Items are numbered "
            "`#1`, `#2`… so you can say \"compare image 1 with image 2\".\n"
        )
        self._add_message("System", help_md)

    def _attach_file(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Attach images or files")
        if paths:
            self._on_files_dropped(paths)

    def _on_files_dropped(self, paths: list):
        added = self.tray.add_paths([str(p) for p in paths])
        if added:
            self.toast_manager.info(f"Se adjuntaron {added} archivo(s)", title="Adjuntos")
        self.input_field.setFocus()

    def _on_image_pasted(self, data: bytes):
        if self.tray.add_image_bytes(data):
            self.toast_manager.info("Se pegó una imagen", title="Adjuntos")

    def _markdown_to_html(self, text_md: str) -> str:
        return markdown.markdown(text_md, extensions=["fenced_code", "tables", "nl2br"])

    def _attachments_html(self, attachments) -> str:
        if not attachments:
            return ""
        t = theme.tokens()
        cells = []
        for a in sorted(attachments, key=lambda x: x.get("index", 0)):
            label = f"#{a.get('index')}"
            if a.get("kind") == "image" and a.get("thumb"):
                url = QUrl.fromLocalFile(a["thumb"]).toString()
                cells.append(
                    f'<td style="padding-right:8px;"><img src="{html.escape(url)}" width="72" height="72"><br>'
                    f'<span style="color:{t["muted"]};font-size:11px;">{label} {html.escape(a.get("name", ""))}</span></td>'
                )
            else:
                cells.append(
                    f'<td style="padding-right:8px;color:{t["muted"]};">{label} '
                    f'{html.escape(a.get("name", "file"))}</td>'
                )
        return f'<table style="margin-top:6px;"><tr>{"".join(cells)}</tr></table>'

    def _add_message(self, sender: str, content_md: str, attachments=None):
        html_content = self._markdown_to_html(content_md) + self._attachments_html(attachments)
        t = theme.tokens()
        if sender == "You":
            accent = t["primary"]
        elif sender == "Assistant":
            accent = t["success"]
        else:
            accent = t["warning"]
        bg = _rgba(accent, 0.10)
        block_html = f"""
        <div style="margin-bottom: 12px; padding: 12px 16px; background-color: {bg}; border-left: 3px solid {accent}; border-radius: 8px;">
            <b style="color: {accent}; font-size: 13px;">{html.escape(sender)}</b>
            <div style="margin-top: 6px; line-height: 1.6; color: {t['text']};">
                {html_content}
            </div>
        </div>
        """
        self.chat_display.append(block_html)

    def _process_slash_command(self, command: str) -> bool:
        parts = command.strip().split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""

        if cmd == "/clear":
            self.chat_display.clear()
            self._add_message("System", "Chat view cleared.")
            return True
        if cmd == "/help":
            self._show_help()
            return True
        if cmd == "/dev":
            self.toggle_dev_action.trigger()
            return True
        if cmd == "/settings":
            self._open_settings()
            return True
        if cmd == "/skills":
            self._open_skills()
            return True
        if cmd == "/mcp":
            self._add_message("System", self._mcp_summary())
            return True
        if cmd == "/new":
            self.history_widget._create_new_chat()
            return True
        if cmd == "/export":
            self._export_chat()
            return True
        if cmd == "/model":
            self._select_model(arg)
            return True
        return False

    def _select_model(self, query: str):
        if not query:
            self.provider_combo.showPopup()
            return
        q = query.casefold()
        for i in range(self.provider_combo.count()):
            label = self.provider_combo.itemText(i).casefold()
            pid = str(self.provider_combo.itemData(i)).casefold()
            if q in (label, pid) or q in label:
                self.provider_combo.setCurrentIndex(i)
                return
        self.toast_manager.warning(f"No hay un modelo que coincida con “{query}”", title="Modelo")

    def _export_chat(self):
        messages = memory.load_chat(self.chat_id)
        if not messages:
            self.toast_manager.warning("No hay mensajes para exportar", title="Exportar")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export chat", f"{self.chat_id}.md", "Markdown (*.md)")
        if not path:
            return
        lines = [f"# {memory.get_chat_title(self.chat_id) or self.chat_id}\n"]
        for msg in messages:
            who = "You" if msg.get("role") == "user" else "Assistant"
            lines.append(f"## {who}\n\n{msg.get('content', '')}\n")
            for a in msg.get("attachments") or []:
                lines.append(f"_Attachment #{a.get('index')}: {a.get('name')}_\n")
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            self.toast_manager.success(f"Se guardó {path.split('/')[-1]}", title="Exportar")
        except OSError as exc:
            self.toast_manager.error(str(exc), title="Exportar")
