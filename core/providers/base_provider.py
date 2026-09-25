"""Common interface every model provider implements."""

import threading
from abc import ABC, abstractmethod
from typing import Any


class RequestCancelled(Exception):
    """Raised inside a provider loop when the user pressed Cancel."""


class BaseProvider(ABC):
    def __init__(self, provider_config: dict[str, Any], tool_registry, logger, max_iterations: int = 8):
        self.config = provider_config
        self.tool_registry = tool_registry
        self.logger = logger
        self.max_iterations = max_iterations
        # Set by AIEngine.process_message(); a per-request threading.Event.
        self.cancel_event: threading.Event | None = None

    def _check_cancelled(self) -> None:
        if self.cancel_event is not None and self.cancel_event.is_set():
            raise RequestCancelled()

    @abstractmethod
    def run(self, user_prompt: str, system_instruction: str) -> str:
        """Run the full agent loop (model call -> tool calls -> model call -> ...)
        and return the final text response."""
        raise NotImplementedError
