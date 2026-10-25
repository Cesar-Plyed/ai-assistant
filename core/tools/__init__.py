# core/tools/__init__.py
"""
Central tool registry.

Every tool is registered once here with a name, description, JSON Schema for
its parameters, and the Python callable that implements it. Providers then
convert this single definition into whatever format they need:
  - OpenAI-compatible providers (LM Studio, Ollama, most cloud APIs) want the
    JSON Schema almost as-is, wrapped in {"type": "function", "function": {...}}.
  - Gemini wants google.genai.types.FunctionDeclaration objects.
  - Anthropic wants {"name", "description", "input_schema"}.

Keeping one registry means a new tool (or a skill-provided tool) is
automatically available to every provider without touching provider code.
"""

import time
from dataclasses import dataclass
from typing import Any, Callable

import config


@dataclass(frozen=True)
class ToolResult:
    """Outcome of one tool execution.

    ``ok`` means the tool was actually invoked and did not raise. A tool may
    still return a business-level error string (for example "Error: file not
    found"); ``failed`` treats those as errors too, for logging and for
    provider-side ``is_error`` flags.
    """

    name: str
    ok: bool
    content: str
    error: str | None = None
    duration_ms: int = 0

    @property
    def failed(self) -> bool:
        return not self.ok or self.content.lstrip().startswith(("Error:", "BLOCKED:"))


_JSON_TYPES: dict[str, Callable[[Any], bool]] = {
    "string": lambda value: isinstance(value, str),
    "integer": lambda value: (
        isinstance(value, int) and not isinstance(value, bool)
    ) or (isinstance(value, float) and value.is_integer()),
    "number": lambda value: isinstance(value, (int, float)) and not isinstance(value, bool),
    "boolean": lambda value: isinstance(value, bool),
    "array": lambda value: isinstance(value, list),
    "object": lambda value: isinstance(value, dict),
}


def _type_matches(expected: Any, value: Any) -> bool:
    if isinstance(expected, list):
        return any(_type_matches(item, value) for item in expected)
    checker = _JSON_TYPES.get(expected)
    return checker(value) if checker else True


def _validate_arguments(schema: dict[str, Any], arguments: dict[str, Any]) -> str | None:
    """Return an error message when arguments obviously violate the schema.

    This is deliberately a small validator (required keys, primitive types and
    enums) rather than a full JSON-Schema implementation: it catches the
    hallucinations models make most often without adding a dependency. Unknown
    keys are left to Python's normal ``TypeError`` so a schema that forgot an
    optional parameter cannot block a valid call.

    ``None`` is accepted for optional properties: local models routinely send
    ``null`` for unused fields, and tools such as ``click_mouse`` use ``None``
    to mean "omit this argument".
    """
    if not isinstance(schema, dict):
        return None
    properties = schema.get("properties")
    properties = properties if isinstance(properties, dict) else {}

    required = schema.get("required")
    required_keys = set(required) if isinstance(required, list) else set()
    if required_keys:
        missing = [key for key in required_keys if key not in arguments]
        if missing:
            return f"missing required argument(s): {', '.join(repr(key) for key in missing)}"

    for key, value in arguments.items():
        spec = properties.get(key)
        if not isinstance(spec, dict):
            continue
        if value is None and key not in required_keys:
            continue
        expected_type = spec.get("type")
        if expected_type is not None and not _type_matches(expected_type, value):
            return (
                f"argument {key!r} must be of type {expected_type!r}, "
                f"got {type(value).__name__}"
            )
        enum = spec.get("enum")
        if isinstance(enum, list) and value not in enum:
            return f"argument {key!r} must be one of {enum!r}, got {value!r}"
    return None


def _coerce_integer_arguments(
    schema: dict[str, Any], arguments: dict[str, Any]
) -> dict[str, Any]:
    """Turn integral floats into ints for ``integer`` properties.

    JSON has one number type, so models often send ``10.0`` where Python needs
    ``10`` (e.g. ``range()`` or a slice). Validation accepts the integral float;
    this makes the value usable by the tool, including nested objects/arrays and
    union types such as ``["integer", "null"]``.
    """
    if not isinstance(schema, dict) or not isinstance(arguments, dict):
        return arguments
    properties = schema.get("properties")
    properties = properties if isinstance(properties, dict) else {}
    return _coerce_object(properties, arguments)


def _coerce_object(
    properties: dict[str, Any], arguments: dict[str, Any]
) -> dict[str, Any]:
    coerced = dict(arguments)
    for key, value in coerced.items():
        spec = properties.get(key)
        if isinstance(spec, dict):
            coerced[key] = _coerce_value(spec, value)
    return coerced


def _coerce_value(spec: dict[str, Any], value: Any) -> Any:
    expected_type = spec.get("type")
    is_integer = expected_type == "integer" or (
        isinstance(expected_type, list) and "integer" in expected_type
    )
    if is_integer and isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, dict):
        properties = spec.get("properties")
        if isinstance(properties, dict):
            return _coerce_object(properties, value)
    if isinstance(value, list):
        items = spec.get("items")
        if isinstance(items, dict):
            return [_coerce_value(items, item) for item in value]
    return value


def _truncate(text: str) -> str:
    """Keep a runaway tool result from swallowing the model's context window."""
    try:
        limit = int(config.SETTINGS.get("max_tool_result_chars", 20000))
    except (TypeError, ValueError):
        limit = 20000
    if limit <= 0 or len(text) <= limit:
        return text
    omitted = len(text) - limit
    return f"{text[:limit]}\n\n[... {omitted} characters omitted; tool result truncated ...]"


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, dict[str, Any]] = {}

    def register(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        func: Callable[..., str],
    ) -> None:
        self._tools[name] = {
            "name": name,
            "description": description,
            "parameters": parameters,
            "func": func,
        }

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def has(self, name: str) -> bool:
        return name in self._tools

    def names(self) -> list[str]:
        return list(self._tools.keys())

    def call_result(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        """Execute a tool and return a structured result instead of a bare string."""
        if name not in self._tools:
            message = f"Error: tool '{name}' is not registered."
            return ToolResult(name=name, ok=False, content=message, error=message)

        if not isinstance(arguments, dict):
            message = (
                f"Error: invalid arguments for tool '{name}': expected a JSON object, "
                f"got {type(arguments).__name__}."
            )
            return ToolResult(name=name, ok=False, content=message, error=message)

        schema = self._tools[name].get("parameters") or {}
        validation_error = _validate_arguments(schema, arguments)
        if validation_error is not None:
            message = f"Error: invalid arguments for tool '{name}': {validation_error}."
            return ToolResult(name=name, ok=False, content=message, error=message)

        arguments = _coerce_integer_arguments(schema, arguments)

        started = time.perf_counter()
        error: str | None = None
        try:
            content = str(self._tools[name]["func"](**arguments))
        except TypeError as e:
            content = f"Error: invalid arguments for tool '{name}': {e}"
            error = content
        except Exception as e:
            content = f"Error while executing tool '{name}': {type(e).__name__}: {e}"
            error = content

        return ToolResult(
            name=name,
            ok=error is None,
            content=_truncate(content),
            error=error,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )

    def call(self, name: str, arguments: dict[str, Any]) -> str:
        """Backward-compatible string API used by skills and older callers."""
        return self.call_result(name, arguments).content

    def as_openai_schema(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool["description"],
                    "parameters": tool["parameters"],
                },
            }
            for tool in self._tools.values()
        ]

    def as_anthropic_schema(self) -> list[dict[str, Any]]:
        return [
            {
                "name": tool["name"],
                "description": tool["description"],
                "input_schema": tool["parameters"],
            }
            for tool in self._tools.values()
        ]

    def as_gemini_declarations(self):
        """Lazily imports google.genai so this module has no hard dependency
        on it (useful if the user only ever uses local providers)."""
        from google.genai import types

        declarations = []
        for tool in self._tools.values():
            declarations.append(
                types.FunctionDeclaration(
                    name=tool["name"],
                    description=tool["description"],
                    parameters=tool["parameters"],
                )
            )
        return [types.Tool(function_declarations=declarations)]


# Global registry instance shared across the app (core tools + skills).
REGISTRY = ToolRegistry()
