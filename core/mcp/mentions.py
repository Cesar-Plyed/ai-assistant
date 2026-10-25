"""Parse ``;server.tool`` / ``;server.tool {json}`` mentions in a user prompt."""

from __future__ import annotations

import json
import re
from typing import Any

_MENTION = re.compile(r"(?:(?<=\s)|^);([A-Za-z0-9_\-]+\.[A-Za-z0-9_.\-]+)")


def extract_mcp_mentions(prompt: str, manager) -> list[tuple[Any, dict[str, Any] | None]]:
    """Return ``[(MCPTool, args_or_None)]`` for mentions of *connected* tools."""
    found: list[tuple[Any, dict[str, Any] | None]] = []
    decoder = json.JSONDecoder()
    tools = {t.mention: t for t in manager.list_tools()}
    for match in _MENTION.finditer(prompt or ""):
        tool = tools.get(match.group(1))
        if tool is None or any(tool is t for t, _ in found):
            continue
        rest = prompt[match.end():].lstrip()
        args = None
        if rest.startswith("{"):
            try:
                value, _ = decoder.raw_decode(rest)
                args = value if isinstance(value, dict) else None
            except ValueError:
                args = None
        found.append((tool, args))
    return found


def mentions_context(mentions: list[tuple[Any, dict[str, Any] | None]]) -> str:
    if not mentions:
        return ""
    lines = ["The user explicitly asked to use these MCP tools for this message:"]
    for tool, args in mentions:
        line = f"- call `{tool.qualified_name}`"
        if args is not None:
            line += f" with exactly these arguments: {json.dumps(args, ensure_ascii=False)}"
        else:
            line += " (choose arguments from the user's description)"
        lines.append(line)
    return "\n".join(lines)
