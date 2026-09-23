"""Dev Mode panel: shows every model request, tool call, tool result, and
final answer as they happen, plus whatever was already logged this session."""

import json

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit

EVENT_COLORS = {
    "user_message": "#569cd6",
    "model_request": "#9cdcfe",
    "model_response": "#4ec9b0",
    "tool_call": "#dcdcaa",
    "tool_result": "#b5cea8",
    "final_answer": "#4ec9b0",
    "error": "#f48771",
}


class DevConsole(QWidget):
    def __init__(self, dev_logger, parent=None):
        super().__init__(parent)
        self.dev_logger = dev_logger

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        header = QHBoxLayout()
        title = QLabel("Dev Mode - Reasoning Log")
        title.setStyleSheet("font-weight: bold; color: #ffffff;")
        self.clear_button = QPushButton("Clear")
        self.clear_button.clicked.connect(self.clear_log)
        header.addWidget(title)
        header.addStretch()
        header.addWidget(self.clear_button)
        layout.addLayout(header)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setStyleSheet(
            "background-color: #1a1a1a; color: #d4d4d4; font-family: monospace; font-size: 12px; border: 1px solid #3c3c3c;"
        )
        layout.addWidget(self.log_view)

        self.dev_logger.event_logged.connect(self.append_event)
        self._load_history()

    def _load_history(self):
        for event in self.dev_logger.tail(200):
            self.append_event(event, persist=False)

    def append_event(self, event: dict, persist: bool = True):
        color = EVENT_COLORS.get(event["type"], "#d4d4d4")
        payload_text = json.dumps(event["payload"], ensure_ascii=False, indent=None, default=str)
        if len(payload_text) > 1200:
            payload_text = payload_text[:1200] + " ...[truncated]"

        line = (
            f'<span style="color:#888;">[{event["timestamp"]}]</span> '
            f'<span style="color:{color}; font-weight:bold;">{event["type"]}</span> '
            f'<span style="color:#cccccc;">{payload_text}</span>'
        )
        self.log_view.append(line)

    def clear_log(self):
        self.log_view.clear()
