# core/tools/__init__.py
"""
Central tool registry.

Every tool is registered once here with a name, description, JSON Schema for
its parameters, and the Python callable that implements it. Providers then
convert this single definition into whatever format they need:
  - OpenAI-compatible providers (LM Studio, Ollama, most cloud APIs) want the
    JSON Schema almost as-is, wrapped in {"type": "function", "function": {...}}.
  - Gemini wants google.genai.types.FunctionDeclaration objects.

Keeping one registry means a new tool (or a skill-provided tool) is
automatically available to every provider without touching provider code.
"""

from typing import Any, Callable


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

    def call(self, name: str, arguments: dict[str, Any]) -> str:
        if name not in self._tools:
            return f"Error: tool '{name}' is not registered."
        try:
            return str(self._tools[name]["func"](**arguments))
        except TypeError as e:
            return f"Error: invalid arguments for tool '{name}': {e}"
        except Exception as e:
            return f"Error while executing tool '{name}': {e}"

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
