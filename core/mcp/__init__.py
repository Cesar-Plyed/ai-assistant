# core/mcp/__init__.py
"""MCP (Model Context Protocol) client support."""

from core.mcp.manager import (
    MCP_TOOL_PREFIX,
    MCPManager,
    MCPServerStatus,
    MCPTool,
)
from core.mcp.registry import register_mcp_tools, unregister_mcp_tools

__all__ = [
    "MCP_TOOL_PREFIX",
    "MCPManager",
    "MCPServerStatus",
    "MCPTool",
    "register_mcp_tools",
    "unregister_mcp_tools",
]
