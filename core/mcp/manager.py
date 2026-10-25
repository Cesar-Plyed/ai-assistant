# core/mcp/manager.py
"""
Minimal MCP (Model Context Protocol) client used by the assistant.

The app is a synchronous Qt application, but the official MCP SDK is async and
a session must stay open for as long as the server is used (especially for
stdio, where closing the session kills the subprocess). This module therefore
runs a single asyncio event loop in a dedicated daemon thread and keeps one
``AsyncExitStack`` per server alive for the whole app session.

Servers come from ``settings.json`` (``mcp_servers``):

    {
      "id": "filesystem",
      "label": "Filesystem",
      "transport": "stdio",            # "stdio" or "http"
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
      "env": {"TOKEN": "..."},
      "url": "",                       # http only
      "headers": {"Authorization": "Bearer ..."},
      "enabled": true
    }

``mcp`` is imported lazily so the rest of the app keeps working when the
optional extra is not installed; each server then reports an actionable error.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import os
import re
import threading
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from typing import Any, Callable

import config

logger = logging.getLogger(__name__)

MCP_TOOL_PREFIX = "mcp__"
DEFAULT_CALL_TIMEOUT = 60.0
DEFAULT_CONNECT_TIMEOUT = 15.0
_LOOP_START_TIMEOUT = 10.0
_LOOP_STOP_TIMEOUT = 5.0

# A connector is anything that returns an async context manager yielding an
# object with ``list_tools()`` and ``call_tool(name, arguments)``. Tests inject
# a fake; production uses the SDK through ``_default_client``.
Connector = Callable[[dict[str, Any], float], Any]


def _slug(value: str) -> str:
    """Turn a server/tool name into a provider-safe identifier."""
    slug = re.sub(r"[^0-9A-Za-z_]+", "_", str(value).strip()).strip("_").lower()
    return slug or "unnamed"


@dataclass(frozen=True)
class MCPTool:
    """One tool exposed by a connected MCP server."""

    server_id: str
    server_label: str
    name: str
    description: str
    input_schema: dict[str, Any]

    @property
    def qualified_name(self) -> str:
        """Name the model sees in the shared tool registry."""
        return f"{MCP_TOOL_PREFIX}{_slug(self.server_id)}__{_slug(self.name)}"

    @property
    def mention(self) -> str:
        """Name the user types after ``;`` in the chat input."""
        return f"{self.server_id}.{self.name}"


@dataclass
class MCPServerStatus:
    """Connection state of one configured server, for the UI and ``/mcp``."""

    server_id: str
    label: str
    transport: str
    enabled: bool = True
    connected: bool = False
    tool_count: int = 0
    error: str | None = None

    def summary(self) -> str:
        if not self.enabled:
            return "disabled"
        if self.connected:
            return f"connected · {self.tool_count} tool(s)"
        return f"error: {self.error or 'not connected'}"


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _server_id(server: dict[str, Any], index: int) -> str:
    raw = str(server.get("id") or server.get("label") or "").strip()
    return raw or f"server_{index + 1}"


def _server_label(server: dict[str, Any], server_id: str) -> str:
    return str(server.get("label") or server_id)


def _tool_from_sdk(server: dict[str, Any], server_id: str, label: str, raw: Any) -> MCPTool | None:
    name = str(getattr(raw, "name", "") or "").strip()
    if not name:
        return None
    schema = getattr(raw, "input_schema", None)
    if not isinstance(schema, dict):
        schema = getattr(raw, "inputSchema", None)
    if not isinstance(schema, dict):
        schema = {"type": "object", "properties": {}}
    return MCPTool(
        server_id=server_id,
        server_label=label,
        name=name,
        description=str(getattr(raw, "description", "") or "").strip(),
        input_schema=schema,
    )


def _format_content(result: Any) -> str:
    """Flatten an MCP ``CallToolResult`` into plain text for the model."""
    parts: list[str] = []
    for item in getattr(result, "content", None) or []:
        if isinstance(item, dict):
            text = item.get("text")
            item_type = item.get("type", "")
        else:
            text = getattr(item, "text", None)
            item_type = getattr(item, "type", "")
        if isinstance(text, str):
            parts.append(text)
        elif item_type == "image":
            parts.append("[image content omitted]")
        else:
            try:
                payload = item.model_dump(mode="json") if hasattr(item, "model_dump") else item
            except Exception:  # pragma: no cover - defensive
                payload = item
            parts.append(json.dumps(payload, ensure_ascii=False, default=str))

    if not parts:
        structured = getattr(result, "structured_content", None)
        if structured not in (None, "", {}, []):
            parts.append(json.dumps(structured, ensure_ascii=False, default=str))

    text = "\n".join(part for part in parts if part).strip() or "(no content returned)"
    if getattr(result, "is_error", False):
        return f"Error: {text}"
    return text


@asynccontextmanager
async def _default_client(server: dict[str, Any], timeout: float):
    """Open a real SDK client for one server, keeping nested resources alive."""
    try:
        from mcp import Client, StdioServerParameters
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise RuntimeError(
            "MCP support is not installed. Install the optional extra with "
            "`uv sync --extra mcp` (or `pip install \"mcp>=2.0\"`)."
        ) from exc

    transport = str(server.get("transport") or "stdio").strip().lower()
    if transport == "stdio":
        command = str(server.get("command") or "").strip()
        if not command:
            raise ValueError("stdio server has no command configured")
        args = [str(arg) for arg in (server.get("args") or [])]
        env = {**os.environ, **_as_dict(server.get("env"))}
        params = StdioServerParameters(command=command, args=args, env=env)
        async with Client(params, read_timeout_seconds=timeout) as client:
            yield client
        return

    if transport != "http":
        raise ValueError(f"unsupported MCP transport {transport!r} (expected 'stdio' or 'http')")

    url = str(server.get("url") or "").strip()
    if not url:
        raise ValueError("HTTP server has no url configured")

    headers = {str(k): str(v) for k, v in _as_dict(server.get("headers")).items()}
    if not headers:
        async with Client(url, read_timeout_seconds=timeout) as client:
            yield client
        return

    try:
        import httpx2
        from mcp.client.streamable_http import streamable_http_client
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise RuntimeError(
            "MCP HTTP headers need the optional MCP dependencies "
            "(`uv sync --extra mcp`)."
        ) from exc

    async with httpx2.AsyncClient(headers=headers, timeout=timeout) as http_client:
        transport_cm = streamable_http_client(url, http_client=http_client)
        async with Client(transport_cm, read_timeout_seconds=timeout) as client:
            yield client


class MCPManager:
    """Connect to configured MCP servers and expose their tools synchronously."""

    def __init__(
        self,
        servers: list[dict[str, Any]] | None = None,
        call_timeout: float | None = None,
        connector: Connector | None = None,
        connect_timeout: float | None = None,
    ):
        self._servers = servers
        self._call_timeout = float(
            call_timeout
            if call_timeout is not None
            else config.SETTINGS.get("mcp_call_timeout", DEFAULT_CALL_TIMEOUT)
        )
        # Starting a server should not hang startup for the full tool timeout.
        self._connect_timeout = float(
            connect_timeout
            if connect_timeout is not None
            else min(self._call_timeout, DEFAULT_CONNECT_TIMEOUT)
        )
        self._connector = connector
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._loop_lock = threading.Lock()
        self._sessions: dict[str, tuple[AsyncExitStack, Any]] = {}
        self._tools: list[MCPTool] = []
        self._status: list[MCPServerStatus] = []
        self._lock = threading.RLock()

    # -- configuration ---------------------------------------------------
    @property
    def call_timeout(self) -> float:
        return self._call_timeout

    @property
    def connect_timeout(self) -> float:
        return self._connect_timeout

    def _configured_servers(self) -> list[dict[str, Any]]:
        if self._servers is not None:
            return list(self._servers)
        servers = config.SETTINGS.get("mcp_servers") or []
        return [server for server in servers if isinstance(server, dict)]

    # -- event loop ------------------------------------------------------
    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        with self._loop_lock:
            if self._loop is not None and self._loop.is_running():
                return self._loop

            ready = threading.Event()

            def runner() -> None:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                self._loop = loop
                ready.set()
                try:
                    loop.run_forever()
                finally:
                    loop.run_until_complete(loop.shutdown_asyncgens())
                    loop.close()

            self._thread = threading.Thread(target=runner, name="mcp-event-loop", daemon=True)
            self._thread.start()
            if not ready.wait(_LOOP_START_TIMEOUT) or self._loop is None:
                raise RuntimeError("could not start the MCP event loop")
            return self._loop

    def _run(self, coro, timeout: float | None = None):
        if self._thread is not None and threading.current_thread() is self._thread:
            raise RuntimeError("MCP manager cannot be called from its own event-loop thread")
        loop = self._ensure_loop()
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        try:
            return future.result(timeout)
        except concurrent.futures.TimeoutError:
            future.cancel()
            raise TimeoutError(f"operation timed out after {timeout:g}s") from None

    # -- connection lifecycle -------------------------------------------
    async def _connect_server(
        self, server: dict[str, Any], server_id: str, label: str
    ) -> tuple[AsyncExitStack, Any, list[MCPTool]]:
        connector = self._connector
        client_cm = (
            connector(server, self._connect_timeout)
            if connector is not None
            else _default_client(server, self._connect_timeout)
        )
        stack = AsyncExitStack()
        try:
            client = await stack.enter_async_context(client_cm)
            result = await client.list_tools()
            tools = [
                tool
                for raw in (getattr(result, "tools", None) or [])
                if (tool := _tool_from_sdk(server, server_id, label, raw)) is not None
            ]
        except BaseException:
            await stack.aclose()
            raise
        return stack, client, tools

    async def _close_sessions(self) -> None:
        sessions = list(self._sessions.values())
        self._sessions.clear()
        for stack, _client in reversed(sessions):
            try:
                await stack.aclose()
            except Exception as exc:  # pragma: no cover - best-effort cleanup
                logger.warning("Error closing MCP session: %s", exc)

    def connect_all(self, servers: list[dict[str, Any]] | None = None) -> list[MCPServerStatus]:
        """(Re)connect every enabled server, replacing any previous sessions.

        Never raises for an individual server: a broken server is reported in
        its status so the app and the remaining servers keep working.
        """
        if servers is not None:
            self._servers = servers
        self.close()

        statuses: list[MCPServerStatus] = []
        tools: list[MCPTool] = []
        seen_qualified: set[str] = set()

        for index, server in enumerate(self._configured_servers()):
            server_id = _server_id(server, index)
            label = _server_label(server, server_id)
            transport = str(server.get("transport") or "stdio").strip().lower()
            enabled = bool(server.get("enabled", True))
            status = MCPServerStatus(
                server_id=server_id,
                label=label,
                transport=transport,
                enabled=enabled,
            )
            statuses.append(status)
            if not enabled:
                continue

            try:
                stack, client, server_tools = self._run(
                    self._connect_server(server, server_id, label),
                    timeout=self._connect_timeout + _LOOP_STOP_TIMEOUT,
                )
            except Exception as exc:
                status.error = f"{type(exc).__name__}: {exc}"
                logger.warning("MCP server %r failed to connect: %s", server_id, status.error)
                continue

            with self._lock:
                self._sessions[server_id] = (stack, client)
            status.connected = True
            for tool in server_tools:
                if tool.qualified_name in seen_qualified:
                    continue
                seen_qualified.add(tool.qualified_name)
                tools.append(tool)
            status.tool_count = len(server_tools)

        with self._lock:
            self._tools = tools
            self._status = statuses
        return list(statuses)

    def close(self) -> None:
        """Close every open session but keep the event loop alive for reconnects."""
        with self._lock:
            has_sessions = bool(self._sessions)
        if has_sessions and self._loop is not None and self._loop.is_running():
            try:
                self._run(self._close_sessions(), timeout=_LOOP_STOP_TIMEOUT)
            except Exception as exc:  # pragma: no cover - best-effort cleanup
                logger.warning("Error closing MCP sessions: %s", exc)
        with self._lock:
            self._sessions.clear()
            self._tools = []
            self._status = []

    def shutdown(self) -> None:
        """Close sessions and stop the background thread (safe to call twice)."""
        self.close()
        loop = self._loop
        thread = self._thread
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(loop.stop)
        if thread is not None and thread.is_alive():
            thread.join(_LOOP_STOP_TIMEOUT)
        self._loop = None
        self._thread = None

    # -- tools -----------------------------------------------------------
    def list_tools(self) -> list[MCPTool]:
        with self._lock:
            return list(self._tools)

    def status(self) -> list[MCPServerStatus]:
        with self._lock:
            return list(self._status)

    def find_tool(self, name: str) -> MCPTool | None:
        """Resolve a qualified name, a ``server.tool`` mention, or a bare tool name."""
        query = str(name or "").strip()
        if not query:
            return None
        with self._lock:
            tools = list(self._tools)
        for tool in tools:
            if query in (tool.qualified_name, tool.mention):
                return tool
        matches = [tool for tool in tools if tool.name == query]
        return matches[0] if len(matches) == 1 else None

    async def _call(self, tool: MCPTool, arguments: dict[str, Any]) -> Any:
        session = self._sessions.get(tool.server_id)
        if session is None:
            raise RuntimeError(f"MCP server {tool.server_id!r} is not connected")
        _stack, client = session
        return await asyncio.wait_for(
            client.call_tool(tool.name, arguments), timeout=self._call_timeout
        )

    def call_tool(self, tool: MCPTool | str, arguments: dict[str, Any] | None = None) -> str:
        """Call a tool and always return text (errors start with ``Error:``)."""
        resolved = tool if isinstance(tool, MCPTool) else self.find_tool(str(tool))
        if resolved is None:
            return f"Error: MCP tool {tool!r} is not available. Is its server connected?"
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            return (
                f"Error: invalid arguments for MCP tool '{resolved.mention}': "
                f"expected a JSON object, got {type(arguments).__name__}."
            )

        try:
            result = self._run(
                self._call(resolved, arguments), timeout=self._call_timeout + _LOOP_STOP_TIMEOUT
            )
        except TimeoutError:
            return (
                f"Error: MCP tool '{resolved.mention}' timed out after "
                f"{self._call_timeout:g}s."
            )
        except Exception as exc:
            return f"Error: MCP tool '{resolved.mention}' failed: {type(exc).__name__}: {exc}"

        try:
            return _format_content(result)
        except Exception as exc:  # pragma: no cover - defensive
            return f"Error: could not read the result of '{resolved.mention}': {exc}"
