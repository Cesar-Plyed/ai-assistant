"""
Reasoning / tool-call logger used by Dev Mode.

Every step the agent takes (sending a prompt to the model, a tool call, a
tool result, the final answer, or an error) is recorded here. Two things
happen with each event:

1. It is appended to a JSONL file under logs/ for later inspection.
2. It is broadcast through a Qt signal so the Dev Console widget can show it
   live, even though the agent loop runs on a background thread.
"""

import json
from datetime import datetime
from typing import Any

from PyQt6.QtCore import QObject, pyqtSignal

from config import DEV_LOG_DIR

EVENT_TYPES = (
    "user_message",
    "model_request",
    "model_response",
    "tool_call",
    "tool_result",
    "final_answer",
    "error",
)


class DevLogger(QObject):
    """Thread-safe event bus. Safe to call .log() from a worker QThread;
    the event_logged signal is queued back to the GUI thread automatically."""

    event_logged = pyqtSignal(dict)

    def __init__(self, session_id: str = "session"):
        super().__init__()
        self.session_id = session_id
        self._log_path = DEV_LOG_DIR / f"{session_id}_dev.jsonl"

    def log(self, event_type: str, payload: dict[str, Any] | None = None) -> None:
        event = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "type": event_type,
            "payload": payload or {},
        }
        try:
            with open(self._log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
        except Exception:
            pass
        self.event_logged.emit(event)

    def tail(self, n: int = 200) -> list[dict]:
        if not self._log_path.exists():
            return []
        with open(self._log_path, "r", encoding="utf-8") as f:
            lines = f.readlines()[-n:]
        events = []
        for line in lines:
            try:
                events.append(json.loads(line))
            except Exception:
                continue
        return events
