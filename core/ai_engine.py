"""
Top-level orchestrator used by the UI.

Responsibilities:
  - Build the shared tool registry (core tools + enabled skills).
  - Pick the provider implementation for the currently active provider config.
  - Run one turn of the conversation and persist it to chat memory.
  - Feed every step to the DevLogger so Dev Mode can show what's happening.
"""

import uuid
from typing import Any

import config
from config import reload_settings, get_active_provider, tools_for_profile
from core.logger import DevLogger
from core.mcp import MCPManager, register_mcp_tools, unregister_mcp_tools
from core.memory import load_chat, save_chat
from core.tools import REGISTRY
from core.tools import filesystem_tools, system_tools, browser_automation, mouse_tools
from core.providers import create_provider
from core.providers.base_provider import RequestCancelled
from core import attachments as attachments_mod
from core import skills_manager
from core.providers.capabilities import get_capabilities
from core.mcp.mentions import extract_mcp_mentions, mentions_context

SYSTEM_INSTRUCTION_TEMPLATE = """You are an advanced desktop assistant for Windows, Linux (including KDE \
Plasma and other desktop environments) and macOS.

OPERATING PRINCIPLES:
- Use the available tools whenever a request requires information about the \
system, files, installed applications, hardware status, or the web, rather \
than guessing.
- Prefer the most specific tool for the job (e.g. get_hardware_status for \
hardware questions, list_installed_applications before opening an app).
- Call tools deliberately: make independent calls together when possible, but \
never guess a later argument before you have the earlier result.
- Never invent or assume tool output. If a tool returns an error, correct the \
arguments and retry at most once, or explain the failure to the user.
- ALL web navigation and page interaction happens through the browser_* tools. \
Open a page with browser_goto, inspect it with browser_read_page or \
browser_list_interactive_elements, then interact with browser_click, browser_fill, \
browser_set_checkbox, browser_select_option, browser_press_key, browser_scroll or \
browser_type_text. They drive the user's automation browser, which is already logged in.
- NEVER click Apply / Submit / Enviar / Postular without asking the user first. If \
browser_click returns BLOCKED, ask for confirmation and only then retry with confirmed=true.
- Mouse/keyboard control tools only work if the user has explicitly enabled \
them in Settings; if a tool reports it is disabled, tell the user how to \
enable it instead of trying repeatedly.
- MCP (Model Context Protocol) tools appear as mcp__<server>__<tool> and are \
provided by external servers the user configured. Use them like any other \
tool; if a server is disconnected, say which one and suggest checking Settings.
- Respond concisely in Markdown. Match the language the user writes in.
- TOOL CALLING PROTOCOL: Always use the provider's native tool-calling channel. \
Never write tool calls as JSON in your response text. If a tool call fails, \
read the error, fix the arguments, and retry at most once. Always end your \
response with natural language for the user — never leave the last message as \
raw tool-call JSON.

{context}
"""


def _build_registry(mcp_manager: MCPManager | None = None):
    """(Re)builds the global tool registry from core tool modules and enabled skills."""
    filesystem_tools.register(REGISTRY)
    system_tools.register(REGISTRY)
    browser_automation.register(REGISTRY)
    mouse_tools.register(REGISTRY)
    skills_manager.load_enabled_skills(REGISTRY)
    # MCP tools are ephemeral: always drop the previous generation before
    # adding the tools of the servers that are connected right now.
    unregister_mcp_tools(REGISTRY)
    if mcp_manager is not None:
        register_mcp_tools(REGISTRY, mcp_manager)
    return REGISTRY


def _provider_run_kwargs(settings: dict) -> dict[str, Any]:
    """Extract provider-level settings from the global settings dict."""
    return {
        "tool_profile": settings.get("tool_profile", "compact"),
        "tool_choice": settings.get("tool_choice", "auto"),
        "parallel_tool_calls": bool(settings.get("parallel_tool_calls", True)),
        "temperature": float(settings.get("temperature", 0.2)),
        "max_tokens": settings.get("max_tokens"),
    }


class AIEngine:
    def __init__(self, chat_id: str = "default_chat"):
        self.chat_id = chat_id
        # The Dev Logger belongs to the app session, not to a single chat, so
        # switching chats doesn't break the Dev Console's live connection to it.
        self.logger = DevLogger(session_id="app")
        self.mcp_manager = MCPManager()
        self.registry = _build_registry(self.mcp_manager)

    def switch_chat(self, new_chat_id: str) -> None:
        """Point the engine at a different chat's memory without losing the
        tool registry or the Dev Mode log connection."""
        self.chat_id = new_chat_id

    def connect_mcp(self):
        """Connect/reconnect every configured MCP server and expose its tools.

        This blocks while servers start (stdio subprocesses), so the UI calls it
        from a worker thread. Individual failures are returned in the statuses.
        """
        statuses = self.mcp_manager.connect_all()
        self.registry = _build_registry(self.mcp_manager)
        self.logger.log(
            "mcp_connect",
            {
                "servers": [
                    {
                        "id": status.server_id,
                        "connected": status.connected,
                        "tools": status.tool_count,
                        "error": status.error,
                    }
                    for status in statuses
                ]
            },
        )
        return statuses

    def close(self) -> None:
        """Release MCP sessions/subprocesses (called when the window closes)."""
        self.mcp_manager.shutdown()

    def get_provider_instance(self):
        provider_config = get_active_provider()
        max_iterations = config.SETTINGS.get("max_agent_iterations", 8)
        run_kwargs = _provider_run_kwargs(config.SETTINGS)
        return create_provider(
            provider_config, self.registry, self.logger, max_iterations, **run_kwargs
        )

    def refresh_settings(self):
        """Call after the Settings/Skills dialogs save changes."""
        reload_settings()
        self.registry = _build_registry(self.mcp_manager)

    def process_message(
        self,
        user_prompt: str,
        save_to_memory: bool = True,
        cancel_event=None,
        use_history: bool = True,
        chat_id: str | None = None,
        attachments: list[dict] | None = None,
        purpose: str = "chat",
    ) -> str:
        # Bind the turn to an explicit id when the caller has one (the worker
        # does), so switching chats cannot redirect the request mid-flight.
        chat_id = chat_id or self.chat_id
        request_id = uuid.uuid4().hex[:12]
        self.logger.log("user_message", {
            "text": user_prompt, "request_id": request_id, "purpose": purpose,
            "chat_id": chat_id,
        })
        history = load_chat(chat_id) if use_history else []
        attachments = list(attachments or [])

        # Skills: compact catalog always; full bodies only for @mentioned skills.
        context_parts = []
        catalog = skills_manager.catalog_text()
        if catalog:
            context_parts.append(catalog)
        mentioned = skills_manager.mentioned_skill_ids(user_prompt) if purpose == "chat" else []
        if mentioned:
            context_parts.append(skills_manager.activated_skills_text(mentioned))
            self.logger.log("skills_activated", {"request_id": request_id, "skills": mentioned})
        if purpose == "chat":
            mcp_ctx = mentions_context(extract_mcp_mentions(user_prompt, self.mcp_manager))
            if mcp_ctx:
                context_parts.append(mcp_ctx)
        # History is passed as real system/user/assistant messages to the
        # provider, not embedded as repr() text in the system prompt.
        system_instruction = SYSTEM_INSTRUCTION_TEMPLATE.format(
            context="\n\n".join(context_parts)
        )
        provider = self.get_provider_instance()
        provider.cancel_event = cancel_event

        # Attachments: numbered manifest always; image pixels only for vision models.
        sent_prompt = user_prompt
        model_attachments: list[dict] = []
        if attachments:
            vision = get_capabilities(get_active_provider()).supports_vision
            sent_prompt = f"{user_prompt}\n\n{attachments_mod.build_manifest(attachments, vision)}"
            if vision:
                model_attachments = attachments
            elif attachments_mod.image_attachments(attachments):
                self.logger.log("attachments_skipped", {
                    "request_id": request_id,
                    "reason": "model has no vision support",
                    "count": len(attachments_mod.image_attachments(attachments)),
                })
        try:
            # Only pass optional kwargs when needed; fake providers in tests
            # may not accept them.
            run_kwargs: dict[str, Any] = {}
            if history:
                run_kwargs["history"] = history
            if model_attachments:
                run_kwargs["attachments"] = model_attachments
            response_text = provider.run(sent_prompt, system_instruction, **run_kwargs)
        except RequestCancelled:
            self.logger.log("error", {"message": "Request cancelled by user.", "request_id": request_id})
            raise
        except Exception as e:
            self.logger.log("error", {"message": str(e), "request_id": request_id})
            raise RuntimeError(f"Error from provider '{self.config_label()}': {e}")
        if save_to_memory:
            if attachments:
                save_chat(chat_id, user_prompt, response_text, attachments=attachments)
            else:
                save_chat(chat_id, user_prompt, response_text)
        self.logger.log(
            "delivered",
            {"request_id": request_id, "chat_id": chat_id, "purpose": purpose,
             "length": len(response_text or "")},
        )
        return response_text

    def config_label(self) -> str:
        return get_active_provider().get("label", "unknown provider")
