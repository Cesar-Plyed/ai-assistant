"""Tests for MCP tool registration in the shared registry."""

from __future__ import annotations

from core.mcp.manager import MCPTool
from core.mcp.registry import register_mcp_tools, unregister_mcp_tools
from core.tools import ToolRegistry


class FakeManager:
    def __init__(self, tools, result="done"):
        self.tools = tools
        self.result = result
        self.calls = []

    def list_tools(self):
        return list(self.tools)

    def call_tool(self, tool, arguments=None):
        self.calls.append((tool, arguments))
        return self.result


def _tool(server_id="fs", name="read_file"):
    return MCPTool(
        server_id=server_id,
        server_label=server_id.upper(),
        name=name,
        description="Read a file",
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    )


def test_register_mcp_tools_exposes_schema_and_calls_manager():
    registry = ToolRegistry()
    manager = FakeManager([_tool()])

    names = register_mcp_tools(registry, manager)

    assert names == ["mcp__fs__read_file"]
    assert registry.has("mcp__fs__read_file")
    schema = registry.as_openai_schema()[0]["function"]
    assert schema["parameters"]["required"] == ["path"]
    assert "MCP · FS" in schema["description"]

    assert registry.call("mcp__fs__read_file", {"path": "/tmp"}) == "done"
    assert manager.calls == [(_tool(), {"path": "/tmp"})]


def test_registration_replaces_previous_mcp_tools_only():
    registry = ToolRegistry()
    registry.register("core_tool", "core", {"type": "object", "properties": {}}, lambda: "ok")
    register_mcp_tools(registry, FakeManager([_tool()]))

    register_mcp_tools(registry, FakeManager([_tool(name="write_file")]))

    assert registry.names() == ["core_tool", "mcp__fs__write_file"]


def test_unregister_mcp_tools_keeps_core_tools():
    registry = ToolRegistry()
    registry.register("core_tool", "core", {"type": "object", "properties": {}}, lambda: "ok")
    register_mcp_tools(registry, FakeManager([_tool()]))

    unregister_mcp_tools(registry)

    assert registry.names() == ["core_tool"]


def test_mcp_tool_validation_error_is_reported_without_calling():
    registry = ToolRegistry()
    manager = FakeManager([_tool()])
    register_mcp_tools(registry, manager)

    result = registry.call_result("mcp__fs__read_file", {})

    assert result.failed
    assert "missing required argument" in result.content
    assert manager.calls == []
