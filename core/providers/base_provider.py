"""Common interface every model provider implements."""

import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from config import tools_for_profile
from core.providers.tool_text import extract_tool_calls
from core.tools import ToolResult
from core.tools.effects import describe_effect


class RequestCancelled(Exception):
    """Raised inside a provider loop when the user pressed Cancel."""


@dataclass(frozen=True)
class TextToolRun:
    """Result of recovering one or more tool calls written as JSON text."""

    payload: str
    tool_names: tuple[str, ...]


class BaseProvider(ABC):
    def __init__(
        self,
        provider_config: dict[str, Any],
        tool_registry,
        logger,
        max_iterations: int = 8,
        tool_profile: str = "compact",
        tool_choice: str = "auto",
        parallel_tool_calls: bool = True,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ):
        self.config = provider_config
        self.tool_registry = tool_registry
        self.logger = logger
        self.max_iterations = max_iterations
        self.tool_profile = tool_profile
        self.tool_choice = tool_choice
        self.parallel_tool_calls = parallel_tool_calls
        self.temperature = temperature
        self.max_tokens = max_tokens
        # Set by AIEngine.process_message(); a per-request threading.Event.
        self.cancel_event: threading.Event | None = None
        # Anti-repeat: (name, frozenset(args.items())) of the last call.
        self._last_tool_call: tuple[str, frozenset] | None = None

    def _check_cancelled(self) -> None:
        if self.cancel_event is not None and self.cancel_event.is_set():
            raise RequestCancelled()

    def _filtered_names(self) -> list[str]:
        """Return the tool names allowed by the active tool profile."""
        return tools_for_profile(self.tool_profile, self.tool_registry.names())

    def _filtered_schema(self) -> list[dict[str, Any]]:
        """Return the OpenAI-format tool schema filtered by the active tool profile."""
        allowed = set(self._filtered_names())
        all_schemas = self.tool_registry.as_openai_schema()
        return [s for s in all_schemas if s["function"]["name"] in allowed]

    def _filtered_anthropic_schema(self) -> list[dict[str, Any]]:
        """Return the Anthropic-format tool schema filtered by the active tool profile."""
        allowed = set(self._filtered_names())
        all_schemas = self.tool_registry.as_anthropic_schema()
        return [s for s in all_schemas if s["name"] in allowed]

    def _filtered_gemini_schema(self):
        """Return the Gemini-format tool schema filtered by the active tool profile."""
        from google.genai import types

        allowed = set(self._filtered_names())
        declarations = self.tool_registry.as_gemini_declarations()[0].function_declarations
        filtered = [d for d in declarations if d.name in allowed]
        return [types.Tool(function_declarations=filtered)]

    def _tool_args_key(self, name: str, arguments: dict[str, Any]) -> Any:
        """Build a hashable key for (name, arguments) to detect repeats."""

        def _freeze(value):
            if isinstance(value, dict):
                return tuple(sorted((k, _freeze(v)) for k, v in value.items()))
            if isinstance(value, (list, tuple, set)):
                return tuple(_freeze(v) for v in value)
            return value

        return (name, _freeze(arguments))

    def _is_repeat(self, name: str, arguments: dict[str, Any]) -> bool:
        key = (name, self._tool_args_key(name, arguments))
        if self._last_tool_call == key:
            return True
        self._last_tool_call = key
        return False

    def _reset_repeat_guard(self) -> None:
        self._last_tool_call = None

    def _log_model_response(self, response, finish_reason: str | None = None,
                            usage: dict | None = None) -> None:
        """Log a model response with finish reason and token usage (best effort)."""
        payload: dict[str, Any] = {}
        if finish_reason:
            payload["finish_reason"] = finish_reason
        if usage:
            payload["usage"] = usage
        if payload:
            self.logger.log("model_response", payload)

    def execute_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        """Run one tool with cancellation checks and consistent Dev Mode logging.

        Providers call this instead of ``tool_registry.call`` so every backend
        reports tool calls, results and errors the same way.
        """
        self._check_cancelled()
        self.logger.log("tool_call", {"name": name, "arguments": arguments})
        result = self.tool_registry.call_result(name, arguments)
        payload = {
            "name": name,
            "arguments": arguments,
            "result": result.content,
            "duration_ms": result.duration_ms,
        }
        if result.failed:
            payload["error"] = result.error or "tool reported an error"
            self.logger.log("tool_error", payload)
        else:
            self.logger.log("tool_result", payload)
            effect = describe_effect(name, arguments)
            if effect is not None:
                self.logger.log("tool_effect", {
                    "tool": name, "title": effect[0], "description": effect[1],
                })
        return result

    def report_tool_error(self, name: str, arguments: Any, message: str) -> ToolResult:
        """Log a tool error that happened before the tool could execute.

        Used for malformed native tool-call arguments, so Dev Mode sees the
        same event shape as ``execute_tool`` failures. The message is
        normalised so the model always sees an ``Error:`` prefix.
        """
        if not message.lstrip().startswith(("Error:", "BLOCKED:")):
            message = f"Error: {message}"
        result = ToolResult(name=name, ok=False, content=message, error=message)
        self.logger.log(
            "tool_error",
            {
                "name": name,
                "arguments": arguments,
                "result": message,
                "error": message,
                "duration_ms": 0,
            },
        )
        return result

    def run_text_tool_calls(self, text: str) -> TextToolRun | None:
        """Execute tool calls that the model wrote as JSON text.

        Returns ``None`` when ``text`` is not a tool call, so ordinary JSON
        answers stay inert. Otherwise the payload is the provider-agnostic user
        message describing each result; providers only need to append it in
        their own wire format.
        """
        calls = extract_tool_calls(text, self.tool_registry)
        if not calls:
            return None

        outputs: list[str] = []
        tool_names: list[str] = []
        for name, arguments in calls:
            result = self.execute_tool(name, arguments)
            tool_names.append(name)
            outputs.append(f"Tool `{name}` returned:\n{result.content}")
        return TextToolRun("\n\n".join(outputs), tuple(tool_names))

    def finalize(self, tool_names: list[str], last_text: str = "") -> str:
        """Return the final answer, logging it once for every provider."""
        text = last_text or self.summarize_tools(tool_names)
        self.logger.log("final_answer", {"text": text})
        self._reset_repeat_guard()
        return text

    def finalize_exhausted(self, tool_names: list[str]) -> str:
        """Return a completion summary when the loop hits ``max_iterations``.

        The last model turn was a tool call (otherwise the loop would have
        returned already), so its text is a preamble or raw tool-call JSON, not
        an answer. Summarising the executed tools is more honest than returning
        that text, and logging ``iteration_limit`` distinguishes a cut-off run
        from a normal completion in Dev Mode.
        """
        self.logger.log(
            "iteration_limit",
            {"tools": tool_names, "max_iterations": self.max_iterations},
        )
        text = self.summarize_tools(tool_names)
        self.logger.log("final_answer", {"text": text})
        self._reset_repeat_guard()
        return text

    def summarize_tools(self, tool_names: list[str]) -> str:
        """Fallback answer when the model used tools but returned no final text."""
        names = list(dict.fromkeys(tool_names))
        if not names:
            return "Action completed."
        return f"Actions completed: {', '.join(names)}."

    @abstractmethod
    def run(self, user_prompt: str, system_instruction: str,
            history: list[dict] | None = None,
            attachments: list[dict] | None = None) -> str:
        """Run the full agent loop (model call -> tool calls -> model call -> ...)
        and return the final text response."""
        raise NotImplementedError
