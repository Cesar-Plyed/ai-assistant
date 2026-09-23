"""Common interface every model provider implements."""

from abc import ABC, abstractmethod
from typing import Any


class BaseProvider(ABC):
    def __init__(self, provider_config: dict[str, Any], tool_registry, logger, max_iterations: int = 8):
        self.config = provider_config
        self.tool_registry = tool_registry
        self.logger = logger
        self.max_iterations = max_iterations

    @abstractmethod
    def run(self, user_prompt: str, system_instruction: str) -> str:
        """Run the full agent loop (model call -> tool calls -> model call -> ...)
        and return the final text response."""
        raise NotImplementedError
