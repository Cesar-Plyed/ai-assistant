"""Recover tool calls that a model wrote as JSON text instead of using the
provider's native tool-calling channel.

Small local models sometimes ignore the ``tools`` parameter and answer with a
JSON object such as::

    {"tool": "list_project_files", "arguments": {"relative_path": "."}}

or a fenced block::

    ```json
    {"tool_calls": [{"name": "browser_goto", "arguments": {"url": "..."}}]}
    ```

This module recognises only shapes that name a *registered* tool **and** carry
an explicit argument object (``arguments``, or ``parameters`` alongside a
``tool`` key), so an ordinary JSON answer (``{"answer": 42}``), a tool inventory
(``[{"name": "browser_close"}]``), or a function definition
(``{"name": ..., "parameters": ...}``) is never executed. A fenced block is
accepted only when it wraps the whole message, not when it is quoted inside
prose.
"""

import json
import re
from typing import Any

_FENCE_RE = re.compile(r"^\s*```(?:json|JSON)?\s*([\[{].*?[\]}])\s*```\s*$", re.DOTALL)


def _strip_code_fence(text: str) -> str:
    match = _FENCE_RE.match(text)
    return match.group(1).strip() if match else text.strip()


def _parse_arguments(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except Exception:
            return None
    return value if isinstance(value, dict) else None


def _parse_one(item: Any, registry) -> list[tuple[str, dict[str, Any]]]:
    if not isinstance(item, dict):
        return []

    # OpenAI-style {"function": {"name": ..., "arguments": ...}}
    function = item.get("function")
    if isinstance(function, dict):
        item = function

    name = item.get("tool") or item.get("name")
    if "arguments" in item:
        raw_arguments = item["arguments"]
    elif isinstance(item.get("tool"), str) and "parameters" in item:
        # Some models use "parameters" for a real call. Only accept it when the
        # name key is "tool": {"name": ..., "parameters": ...} is the standard
        # shape of a function *definition*, which must stay inert.
        raw_arguments = item["parameters"]
    else:
        # No explicit argument object: this is a tool description or a plan,
        # not a call. Requiring the key also blocks bare {"name": "<tool>"}.
        raw_arguments = None

    arguments = _parse_arguments(raw_arguments)
    if isinstance(name, str) and arguments is not None and registry.has(name):
        return [(name, arguments)]

    # Shorthand {"tool_name": {...arguments...}}
    if len(item) == 1:
        key, value = next(iter(item.items()))
        arguments = _parse_arguments(value)
        if isinstance(key, str) and arguments is not None and registry.has(key):
            return [(key, arguments)]

    return []


def extract_tool_calls(content: str | None, registry) -> list[tuple[str, dict[str, Any]]]:
    """Return [(tool_name, arguments), ...] when ``content`` is a tool call."""
    if not isinstance(content, str) or not content:
        return []
    raw = _strip_code_fence(content)
    if not raw or not raw.startswith(("{", "[")):
        return []
    try:
        data = json.loads(raw)
    except Exception:
        return []

    calls: list[tuple[str, dict[str, Any]]] = []
    if isinstance(data, list):
        for item in data:
            calls.extend(_parse_one(item, registry))
        return calls
    if not isinstance(data, dict):
        return []

    batch = data.get("tool_calls")
    if isinstance(batch, list):
        for item in batch:
            calls.extend(_parse_one(item, registry))
    else:
        calls.extend(_parse_one(data, registry))
    return calls
