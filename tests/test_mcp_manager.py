"""Tests for the MCP client manager.

The SDK is optional, so most tests inject a fake connector. One end-to-end test
launches a real stdio server when ``mcp`` is installed.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import textwrap
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from core.mcp.manager import MCPManager, MCPTool


class FakeContent:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class FakeCallResult:
    def __init__(self, text="ok", is_error=False, structured=None):
        self.content = [FakeContent(text)]
        self.is_error = is_error
        self.structured_content = structured


class FakeRawTool:
    def __init__(self, name, description="", schema=None):
        self.name = name
        self.description = description
        self.input_schema = schema or {"type": "object", "properties": {}}


class FakeListResult:
    def __init__(self, tools):
        self.tools = tools


class FakeClient:
    def __init__(self, server, closed):
        self.server = server
        self.closed = closed
        self.calls = []

    async def list_tools(self):
        if self.server.get("fail"):
            raise RuntimeError("boom")
        return FakeListResult(
            [FakeRawTool("read_file", "Read a file", {"type": "object", "properties": {"path": {"type": "string"}}})]
        )

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        if self.server.get("sleep"):
            await asyncio.sleep(self.server["sleep"])
        if self.server.get("error"):
            return FakeCallResult("bad input", is_error=True)
        return FakeCallResult(f"called {name} with {arguments}")


def fake_connector(servers, closed):
    @asynccontextmanager
    async def connect(server, timeout):
        if server.get("connect_error"):
            raise RuntimeError(server["connect_error"])
        client = FakeClient(server, closed)
        try:
            yield client
        finally:
            closed.append(server.get("id"))

    return connect


SERVERS = [
    {"id": "fs", "label": "Filesystem", "transport": "stdio", "command": "fake"},
    {"id": "web", "label": "Web", "transport": "http", "url": "http://localhost/mcp"},
]


@pytest.fixture
def closed():
    return []


@pytest.fixture
def manager(closed):
    mgr = MCPManager(servers=SERVERS, call_timeout=5, connector=fake_connector(SERVERS, closed))
    yield mgr
    mgr.shutdown()


def test_connect_all_registers_tools_with_qualified_names(manager):
    statuses = manager.connect_all()

    assert [status.connected for status in statuses] == [True, True]
    assert all(status.tool_count == 1 for status in statuses)
    tools = manager.list_tools()
    assert [tool.qualified_name for tool in tools] == [
        "mcp__fs__read_file",
        "mcp__web__read_file",
    ]
    assert tools[0].mention == "fs.read_file"
    assert tools[0].description == "Read a file"


def test_disabled_server_is_reported_but_not_connected(closed):
    servers = [dict(SERVERS[0], enabled=False)]
    mgr = MCPManager(servers=servers, connector=fake_connector(servers, closed))
    try:
        statuses = mgr.connect_all()
        assert statuses[0].enabled is False
        assert statuses[0].connected is False
        assert mgr.list_tools() == []
    finally:
        mgr.shutdown()


def test_connection_error_is_isolated_per_server(closed):
    servers = [
        {"id": "broken", "label": "Broken", "connect_error": "nope"},
        SERVERS[0],
    ]
    mgr = MCPManager(servers=servers, connector=fake_connector(servers, closed))
    try:
        statuses = mgr.connect_all()
        assert statuses[0].connected is False
        assert "nope" in statuses[0].error
        assert statuses[1].connected is True
        assert [tool.server_id for tool in mgr.list_tools()] == ["fs"]
    finally:
        mgr.shutdown()


def test_find_tool_accepts_qualified_mention_and_bare_names(manager):
    manager.connect_all()
    tool = manager.find_tool("mcp__fs__read_file")
    assert isinstance(tool, MCPTool) and tool.server_id == "fs"
    assert manager.find_tool("fs.read_file") is tool
    assert manager.find_tool("read_file") is None  # ambiguous across servers
    assert manager.find_tool("missing") is None


def test_call_tool_returns_text_and_error_prefix(manager, closed):
    manager.connect_all()
    assert manager.call_tool("fs.read_file", {"path": "/tmp"}) == "called read_file with {'path': '/tmp'}"

    servers = [dict(SERVERS[0], error=True)]
    mgr = MCPManager(servers=servers, connector=fake_connector(servers, closed))
    try:
        mgr.connect_all()
        assert mgr.call_tool("fs.read_file", {}) == "Error: bad input"
    finally:
        mgr.shutdown()


def test_call_unknown_tool_returns_error(manager):
    manager.connect_all()
    assert manager.call_tool("fs.nope", {}).startswith("Error: MCP tool")


def test_call_tool_timeout_is_reported(closed):
    servers = [dict(SERVERS[0], sleep=1)]
    mgr = MCPManager(servers=servers, call_timeout=0.05, connector=fake_connector(servers, closed))
    try:
        mgr.connect_all()
        message = mgr.call_tool("fs.read_file", {})
        assert message.startswith("Error:")
        assert "timed out" in message
    finally:
        mgr.shutdown()


def test_shutdown_closes_sessions_and_is_idempotent(manager, closed):
    manager.connect_all()
    manager.shutdown()
    assert closed == ["web", "fs"]
    assert manager.call_tool("fs.read_file", {}).startswith("Error:")
    manager.shutdown()  # must not raise


def test_missing_sdk_reports_actionable_error(closed, monkeypatch):
    def missing(server, timeout):
        raise RuntimeError(
            "MCP support is not installed. Install the optional extra with "
            "`uv sync --extra mcp`."
        )

    mgr = MCPManager(servers=[SERVERS[0]], connector=None)
    monkeypatch.setattr("core.mcp.manager._default_client", missing)
    try:
        statuses = mgr.connect_all()
        assert statuses[0].connected is False
        assert "uv sync --extra mcp" in statuses[0].error
    finally:
        mgr.shutdown()


@pytest.mark.skipif(importlib.util.find_spec("mcp") is None, reason="mcp extra not installed")
def test_stdio_end_to_end_with_real_server(tmp_path: Path):
    server_file = tmp_path / "echo_server.py"
    server_file.write_text(
        textwrap.dedent(
            """
            from mcp.server import MCPServer

            server = MCPServer("echo")

            @server.tool()
            def echo(text: str) -> str:
                return f"echo: {text}"

            if __name__ == "__main__":
                server.run(transport="stdio")
            """
        )
    )
    servers = [
        {
            "id": "echo",
            "label": "Echo",
            "transport": "stdio",
            "command": sys.executable,
            "args": [str(server_file)],
        }
    ]
    mgr = MCPManager(servers=servers, call_timeout=20)
    try:
        statuses = mgr.connect_all()
        assert statuses[0].connected, statuses[0].error
        assert mgr.list_tools()[0].name == "echo"
        assert mgr.call_tool("echo.echo", {"text": "hi"}) == "echo: hi"
    finally:
        mgr.shutdown()
