import sys
import threading
import markdown
from PyQt6.QtCore import QThread, pyqtSignal, QTimer, Qt
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QTextBrowser, QLineEdit,
    QPushButton, QLabel, QComboBox, QDockWidget, QFileDialog, QMenuBar,
)

import config
from core import memory
from core.ai_engine import AIEngine
from core.providers.base_provider import RequestCancelled
from core.tools.filesystem_tools import import_uploaded_file
from ui.icons import get_icon
from ui.dev_console import DevConsole
from ui.hardware_widget import HardwareWidget
from ui.settings_dialog import SettingsDialog
from ui.skills_dialog import SkillsDialog
from ui.chat_history_widget import ChatHistoryWidget


class AIWorker(QThread):
    response_ready = pyqtSignal(str, str)   # (chat_id, text)
    error_occurred = pyqtSignal(str, str)   # (chat_id, error message)

    def __init__(self, ai_engine, chat_id, prompt):
        super().__init__()
        self.ai_engine = ai_engine
        self.chat_id = chat_id
        self.prompt = prompt
        self.cancel_event = threading.Event()

    @property
    def was_cancelled(self) -> bool:
        return self.cancel_event.is_set()

    def cancel(self):
        """Ask the agent loop to stop. It stops at the next step boundary."""
        self.cancel_event.set()

    def run(self):
        try:
            result = self.ai_engine.process_message(self.prompt, cancel_event=self.cancel_event)
            if not self.was_cancelled:
                self.response_ready.emit(self.chat_id, result)
        except RequestCancelled:
            pass  # the UI is restored by MainWindow._on_worker_finished
        except Exception as e:
            if not self.was_cancelled:
                self.error_occurred.emit(self.chat_id, str(e))


class TitleWorker(QThread):
    title_generated = pyqtSignal(str, str)  # (old_chat_id, new_title)

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
            title = self.ai_engine.process_message(prompt, save_to_memory=False, cancel_event=self.cancel_event).strip()
            clean_title = "".join(c for c in title if c.isalnum() or c in (" ", "_", "-")).strip()
            clean_title = clean_title.replace(" ", "_")
            if clean_title:
                self.title_generated.emit(self.chat_id, clean_title[:35])
        except Exception:
            pass


class ReasoningSpinner(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        self.label = QLabel("Thinking and running actions")
        self.label.setStyleSheet("color: #888888; font-style: italic; font-size: 13px;")
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
        self.title_worker: TitleWorker | None = None
        
        # Check if chat is brand new
        existing_messages = memory.load_chat(self.chat_id)
        self.is_first_message = len(existing_messages) == 0

        self._init_ui()
        self._load_chat_history()

    def _init_ui(self):
        self.setWindowTitle(f"AI Desktop Assistant - [{self.chat_id}]")
        self.resize(1000, 700)
        self._apply_dark_theme()
        self._build_menu()

        layout = QVBoxLayout()
        layout.setSpacing(10)

        # Top bar
        top_bar = QHBoxLayout()
        status_label = QLabel("Active model:")
        status_label.setStyleSheet("color: #ffffff; font-weight: bold; font-size: 13px;")

        self.provider_combo = QComboBox()
        self._populate_provider_combo()
        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)

        top_bar.addWidget(status_label)
        top_bar.addWidget(self.provider_combo)
        top_bar.addStretch()
        layout.addLayout(top_bar)

        # Chat view
        self.chat_display = QTextBrowser()
        self.chat_display.setOpenExternalLinks(True)
        layout.addWidget(self.chat_display)

        # Bottom section
        bottom_container = QVBoxLayout()
        self.spinner = ReasoningSpinner()
        self.spinner.hide()
        bottom_container.addWidget(self.spinner)

        input_layout = QHBoxLayout()
        self.attach_button = QPushButton()
        self.attach_button.setIcon(get_icon("upload"))
        self.attach_button.setToolTip("Attach a file")
        self.attach_button.clicked.connect(self._attach_file)

        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("Type an instruction or question...")
        self.input_field.returnPressed.connect(self._send_message)

        self.send_button = QPushButton("Send")
        self.send_button.setIcon(get_icon("send"))
        self.send_button.clicked.connect(self._send_message)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setIcon(get_icon("stop"))
        self.cancel_button.setStyleSheet("background-color: #d9534f; color: white; font-weight: bold;")
        self.cancel_button.clicked.connect(self._cancel_request)
        self.cancel_button.hide()

        input_layout.addWidget(self.attach_button)
        input_layout.addWidget(self.input_field)
        input_layout.addWidget(self.send_button)
        input_layout.addWidget(self.cancel_button)

        bottom_container.addLayout(input_layout)
        layout.addLayout(bottom_container)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        self._build_docks()
        self._apply_dev_mode_visibility()

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

        # Right Dock: Dev Console
        self.dev_dock = QDockWidget("Dev Mode", self)
        self.dev_console = DevConsole(self.ai_engine.logger)
        self.dev_dock.setWidget(self.dev_console)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dev_dock)

        # Right Dock: Hardware Monitor
        self.hw_dock = QDockWidget("Hardware Monitor", self)
        self.hardware_widget = HardwareWidget()
        self.hw_dock.setWidget(self.hardware_widget)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.hw_dock)

    def _load_chat_history(self):
        """Loads and displays existing chat history from memory storage."""
        self.chat_display.clear()
        messages = memory.load_chat(self.chat_id)
        
        if messages:
            for msg in messages:
                role = msg.get("role", "assistant")
                sender = "You" if role == "user" else "Assistant" if role == "assistant" else "System"
                self._add_message(sender, msg.get("content", ""))
        else:
            self._add_message("Assistant", f"Ready. Active model: **{self.ai_engine.config_label()}**.")

    def _on_chat_selected(self, new_chat_id: str):
        self.chat_id = new_chat_id
        self.setWindowTitle(f"AI Desktop Assistant - [{self.chat_id}]")
        self.ai_engine.switch_chat(new_chat_id)   # was: self.ai_engine = AIEngine(...)
        existing_messages = memory.load_chat(self.chat_id)
        self.is_first_message = len(existing_messages) == 0
        self._load_chat_history()

    def _send_message(self):
        text = self.input_field.text().strip()
        if not text:
            return

        if text.startswith("/") and self._process_slash_command(text):
            self.input_field.clear()
            return

        self._add_message("You", text)
        self.input_field.clear()

        self.send_button.hide()
        self.cancel_button.show()
        self.input_field.setEnabled(False)
        self.spinner.start()

        # Generate automatic title if this is the first message
        if self.is_first_message:
            self._generate_auto_title(text)
            self.is_first_message = False
            
        self.worker = AIWorker(self.ai_engine, self.chat_id, text)
        self.worker.response_ready.connect(self._receive_response)
        self.worker.error_occurred.connect(self._handle_error)
        self.worker.finished.connect(self._on_worker_finished)
        self.worker.start()

    def _generate_auto_title(self, first_message: str):
        self.title_worker = TitleWorker(self.ai_engine, self.chat_id, first_message)
        self.title_worker.title_generated.connect(self._on_title_generated)
        self.title_worker.start()

    def _on_title_generated(self, old_chat_id: str, new_title: str):
        if old_chat_id != self.chat_id:
            return

        if memory.rename_chat(old_chat_id, new_title):
            self.chat_id = new_title
            self.setWindowTitle(f"AI Desktop Assistant - [{self.chat_id}]")
            self.ai_engine.chat_id = new_title
            self.history_widget.current_chat_id = new_title
            self.history_widget.refresh()

    def _receive_response(self, chat_id: str, response: str):
        self.spinner.stop()
        if chat_id == self.chat_id:
            self._add_message("Assistant", response)
        self._reset_input_state()
        self.history_widget.refresh()

    def _handle_error(self, chat_id: str, error_message: str):
        self.spinner.stop()
        self._add_message("System", f"**Error:** {error_message}")
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
        for worker in (self.worker, self.title_worker):
            if worker is not None and worker.isRunning():
                worker.cancel()
                worker.wait(3000)
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
        self._add_message("System", f"Switched active model to **{self.ai_engine.config_label()}**.")

    def _open_settings(self):
        dialog = SettingsDialog(self)
        if dialog.exec():
            self.ai_engine.refresh_settings()
            self._populate_provider_combo()
            self._apply_dev_mode_visibility()
            self._add_message("System", "Settings saved.")

    def _open_skills(self):
        dialog = SkillsDialog(self)
        if dialog.exec():
            self.ai_engine.refresh_settings()
            self._add_message("System", "Skills updated.")

    def _toggle_dev_mode(self, checked: bool):
        settings = dict(config.SETTINGS)
        settings["dev_mode"] = checked
        config.save_settings(settings)
        config.reload_settings()
        self._apply_dev_mode_visibility()

    def _toggle_hardware_panel(self, checked: bool):
        self.hw_dock.setVisible(checked)

    def _apply_dev_mode_visibility(self):
        visible = config.SETTINGS.get("dev_mode", False)
        self.dev_dock.setVisible(visible)
        self.toggle_dev_action.setChecked(visible)

    def _show_help(self):
        help_md = (
            "**Quick commands:**\n"
            "- Attach a file with the paperclip button before asking a question about it.\n"
            "- Switch active model from top dropdown.\n"
            "- Open **Settings** to add or edit model providers.\n"
            "- Open **Skills** to manage tool extensions.\n"
            "- Toggle **Dev Mode** panel to inspect reasoning and tool-call logs.\n"
        )
        self._add_message("System", help_md)

    def _attach_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Attach a file")
        if not file_path:
            return
        result = import_uploaded_file(file_path)
        self._add_message("System", f"Attached: `{file_path}`\n\n{result}")
        self.input_field.setText(f"About file attached ({file_path}): ")
        self.input_field.setFocus()

    def _apply_dark_theme(self):
        self.setStyleSheet("""
            QMainWindow { background-color: #1e1e1e; }
            QDialog, QMessageBox, QInputDialog {
                background-color: #1e1e1e;
                color: #ffffff;
            }

            QCheckBox, QRadioButton {
                color: #ffffff;
                spacing: 6px;
            }
            QCheckBox::indicator, QRadioButton::indicator {
                width: 16px;
                height: 16px;
                border: 1px solid #555555;
                border-radius: 3px;
                background-color: #2b2b2b;
            }
            QCheckBox::indicator:checked, QRadioButton::indicator:checked {
                background-color: #0e639c;
                border-color: #0e639c;
            }
            
            QLabel { color: #ffffff; }
            QTextBrowser { background-color: #252526; color: #d4d4d4; border: 1px solid #3c3c3c; border-radius: 6px; padding: 12px; font-size: 14px; }
            QLineEdit { background-color: #3c3c3c; color: #ffffff; border: 1px solid #555555; border-radius: 4px; padding: 8px 12px; font-size: 14px; }
            
            QPushButton { background-color: #0e639c; color: #ffffff; border: none; border-radius: 4px; padding: 8px 16px; font-size: 14px; font-weight: bold; }
            QPushButton:hover { background-color: #1177bb; }

            QDialog QPushButton, QMessageBox QPushButton, QInputDialog QPushButton {
                background-color: transparent;
                color: #ffffff;
                border: none;
                border-radius: 4px;
                padding: 6px 16px;
                font-weight: bold;
            }
            QDialog QPushButton:hover, QMessageBox QPushButton:hover, QInputDialog QPushButton:hover {
                background-color: #222222;
                border-color: #888888;
            }

            QDialog QPushButton[text="Cancel"], QDialog QPushButton[text="&Cancel"],
            QDialog QPushButton[text="No"], QDialog QPushButton[text="&No"],
            QMessageBox QPushButton[text="Cancel"], QMessageBox QPushButton[text="&Cancel"],
            QMessageBox QPushButton[text="No"], QMessageBox QPushButton[text="&No"] {
                background-color: #d9534f;
                color: #ffffff;
                border: none;
            }
            QDialog QPushButton[text="Cancel"]:hover, QDialog QPushButton[text="&Cancel"]:hover,
            QDialog QPushButton[text="No"]:hover, QDialog QPushButton[text="&No"]:hover,
            QMessageBox QPushButton[text="Cancel"]:hover, QMessageBox QPushButton[text="&Cancel"]:hover,
            QMessageBox QPushButton[text="No"]:hover, QMessageBox QPushButton[text="&No"]:hover {
                background-color: #c9302c;
            }

             QSpinBox, QDoubleSpinBox {
                background-color: #3c3c3c;
                color: #ffffff;
                border: 1px solid #555555;
                border-radius: 4px;
                padding: 4px 8px;
            }       

            QComboBox { background-color: #3c3c3c; color: #ffffff; border: 1px solid #555555; border-radius: 4px; }
            QComboBox::drop-down {
                border: none;
                width: 0px;
                background: transparent;
            }
            QComboBox QAbstractItemView {
                background-color: #2b2b2b;
                color: #ffffff;
                border: 1px solid #3c3c3c;
                selection-background-color: #0e639c;
                selection-color: #ffffff;
                outline: none;
            }
            QMenuBar { background-color: #1e1e1e; color: #d4d4d4; }
            QMenuBar::item:selected { background-color: #3c3c3c; }
            QMenu { background-color: #000000; color: #ffffff; border: 1px solid #3c3c3c; }
            QMenu::item:selected { background-color: #222222; color: #ffffff; }

            QDockWidget { color: #d4d4d4; }
            QDockWidget::title { background-color: #1e1e1e; color: #ffffff; padding: 6px; }
            QListWidget { background-color: #252526; color: #d4d4d4; border: 1px solid #3c3c3c; border-radius: 4px; }
            QListWidget::item:selected { background-color: #0e639c; color: #ffffff; }
            QGroupBox { color: #d4d4d4; }
        """)

    def _markdown_to_html(self, text_md: str) -> str:
        return markdown.markdown(text_md, extensions=["fenced_code", "tables", "nl2br"])

    def _add_message(self, sender: str, content_md: str):
        html_content = self._markdown_to_html(content_md)
        sender_color = "#4ec9b0" if sender == "Assistant" else "#569cd6" if sender == "You" else "#dcdcaa"

        block_html = f"""
        <div style="margin-bottom: 15px;">
            <b style="color: {sender_color}; font-size: 15px;">{sender}:</b>
            <div style="margin-top: 5px; line-height: 1.5;">
                {html_content}
            </div>
        </div>
        <hr style="border: 0; height: 1px; background: #3c3c3c; margin-bottom: 15px;">
        """
        self.chat_display.append(block_html)

    def _process_slash_command(self, command: str) -> bool:
        cmd = command.lower().strip()

        if cmd in ("/clear",):
            self.chat_display.clear()
            self._add_message("System", "Chat view cleared.")
            return True

        if cmd in ("/help",):
            self._show_help()
            return True

        if cmd in ("/dev",):
            self.toggle_dev_action.trigger()
            return True

        return False