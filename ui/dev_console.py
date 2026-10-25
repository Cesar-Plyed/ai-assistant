"""Dev Mode panel: shows every model request, tool call, tool result, and
final answer as they happen, plus whatever was already logged this session."""

import json

from ui import theme

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QTextEdit, QVBoxLayout, QWidget,
)

# Event type -> theme token name (resolved at render time so Light/Dark both work).
EVENT_TOKENS = {
    "user_message": "primary", "model_request": "accent2", "model_response": "success",
    "tool_call": "warning", "tool_result": "info", "tool_error": "error",
    "final_answer": "success", "error": "error", "iteration_limit": "warning",
    "reasoning_content": "accent2", "delivered": "success", "mcp_connect": "info",
    "tool_effect": "success", "skills_activated": "accent2", "attachments_skipped": "warning",
}


def event_color(event_type: str) -> str:
    t = theme.tokens()
    return t[EVENT_TOKENS.get(event_type, "text")]


_FONT_MONO = "'JetBrains Mono', 'Fira Code', monospace"


def _format_payload(payload: dict) -> str:
    """Format a payload dict for display, highlighting key fields."""
    parts = []
    # Order matters: show the most important fields first.
    for key in ("request_id", "purpose", "finish_reason", "usage", "text",
                "name", "arguments", "result", "error", "duration_ms",
                "message", "chat_id", "length", "tools", "max_iterations"):
        if key in payload:
            value = payload[key]
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False)
            parts.append(f"{key}={value}")
    # Append any remaining keys not already shown.
    shown = set(parts)  # not exact but fine for dedup
    for key, value in payload.items():
        key_str = f"{key}="
        if not any(p.startswith(key_str) for p in parts):
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False)
            parts.append(f"{key}={value}")
    return " ".join(parts)


class DevConsole(QWidget):
    def __init__(self, dev_logger, parent=None):
        super().__init__(parent)
        self.dev_logger = dev_logger

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.setSpacing(8)
        title = QLabel("Dev Mode — Reasoning Log")
        title.setStyleSheet(f"font-weight: 600; font-family: {_FONT_MONO}; font-size: 13px;")
        self.clear_button = QPushButton("Clear")
        self.clear_button.setProperty("secondary", True)
        self.clear_button.clicked.connect(self.clear_log)
        header.addWidget(title)
        header.addStretch()
        header.addWidget(self.clear_button)
        layout.addLayout(header)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setStyleSheet(f"font-family: {_FONT_MONO}; font-size: 12px;")
        layout.addWidget(self.log_view)

        self.dev_logger.event_logged.connect(self.append_event)
        self._load_history()

    def _load_history(self):
        for event in self.dev_logger.tail(200):
            self.append_event(event, persist=False)

    def append_event(self, event: dict, persist: bool = True):
        color = event_color(event["type"])
        t = theme.tokens()
        event_type = event["type"]
        payload = event["payload"]
        payload_text = _format_payload(payload)
        if len(payload_text) > 1200:
            payload_text = payload_text[:1200] + " ...[truncated]"

        # Add a visual tag for delivered events.
        tag = ""
        if event_type == "delivered":
            tag = f' <span style="color:{t["success"]};">[✓ delivered]</span>'
        elif event_type == "iteration_limit":
            tag = f' <span style="color:{t["warning"]};">[⚠ iteration limit]</span>'
        elif event_type == "reasoning_content":
            tag = f' <span style="color:{t["accent2"]};">[thinking]</span>'

        line = (
            f'<span style="color:{t["muted"]};">[{event["timestamp"]}]</span> '
            f'<span style="color:{color}; font-weight:600;">{event_type}</span>{tag} '
            f'<span style="color:{t["log_text"]};">{payload_text}</span>'
        )
        self.log_view.append(line)

    def clear_log(self):
        self.log_view.clear()
