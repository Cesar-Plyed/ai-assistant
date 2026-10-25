# core/mcp/registry.py
"""
Bridge MCP tools into the shared tool registry.

The model calls MCP tools exactly like core tools; the only difference is the
``mcp__server__tool`` name. Registration is rebuilt whenever servers reconnect
so removed servers cannot leave stale tools behind.
"""

from __future__ import annotations

from typing import Any

from core.mcp.manager import MCP_TOOL_PREFIX, MCPManager, MCPTool


def _description(tool: MCPTool) -> str:
    base = tool.description or f"MCP tool '{tool.name}' from {tool.server_label}."
    return (
        f"[MCP · {tool.server_label}] {base}\n"
        f"User mention: ;{tool.mention}"
    )


def register_mcp_tools(registry: Any, manager: MCPManager) -> list[str]:
    """Register every tool of every connected server. Returns the tool names."""
    unregister_mcp_tools(registry)
    registered: list[str] = []

    for tool in manager.list_tools():
        def call_mcp(_tool: MCPTool = tool, **arguments: Any) -> str:
            return manager.call_tool(_tool, arguments)

        registry.register(
            name=tool.qualified_name,
            description=_description(tool),
            parameters=tool.input_schema or {"type": "object", "properties": {}},
            func=call_mcp,
        )
        registered.append(tool.qualified_name)
    return registered


def unregister_mcp_tools(registry: Any) -> None:
    """Remove tools registered by a previous MCP connection."""
    for name in list(registry.names()):
        if name.startswith(MCP_TOOL_PREFIX):
            registry.unregister(name)
