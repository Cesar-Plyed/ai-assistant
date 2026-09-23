"""
Top-level orchestrator used by the UI.

Responsibilities:
  - Build the shared tool registry (core tools + enabled skills).
  - Pick the provider implementation for the currently active provider config.
  - Run one turn of the conversation and persist it to chat memory.
  - Feed every step to the DevLogger so Dev Mode can show what's happening.
"""

import config
from config import reload_settings, get_active_provider
from core.logger import DevLogger
from core.memory import load_chat, save_chat
from core.tools import REGISTRY
from core.tools import filesystem_tools, system_tools, browser_tools, mouse_tools
from core import skills_manager

SYSTEM_INSTRUCTION_TEMPLATE = """You are an advanced desktop assistant for Windows and Linux (including KDE \
Plasma and other Linux desktop environments).

OPERATING PRINCIPLES:
- Use the available tools whenever a request requires information about the \
system, files, installed applications, hardware status, or the web, rather \
than guessing.
- Prefer the most specific tool for the job (e.g. get_hardware_status for \
hardware questions, list_installed_applications before opening an app).
- Mouse/keyboard control tools only work if the user has explicitly enabled \
them in Settings; if a tool reports it is disabled, tell the user how to \
enable it instead of trying repeatedly.
- Respond concisely in Markdown. Match the language the user writes in.

{context}
"""


def _build_registry():
    """(Re)builds the global tool registry from core tool modules and enabled skills."""
    filesystem_tools.register(REGISTRY)
    system_tools.register(REGISTRY)
    browser_tools.register(REGISTRY)
    mouse_tools.register(REGISTRY)
    skills_manager.load_enabled_skills(REGISTRY)
    return REGISTRY


class AIEngine:
    def __init__(self, chat_id: str = "default_chat"):
        self.chat_id = chat_id
        # The Dev Logger belongs to the app session, not to a single chat, so
        # switching chats doesn't break the Dev Console's live connection to it.
        self.logger = DevLogger(session_id="app")
        self.registry = _build_registry()

    def switch_chat(self, new_chat_id: str) -> None:
        """Point the engine at a different chat's memory without losing the
        tool registry or the Dev Mode log connection."""
        self.chat_id = new_chat_id

    def get_provider_instance(self):
        provider_config = get_active_provider()
        provider_type = provider_config.get("type")
        max_iterations = config.SETTINGS.get("max_agent_iterations", 8)

        if provider_type == "gemini":
            from core.providers.gemini_provider import GeminiProvider
            return GeminiProvider(provider_config, self.registry, self.logger, max_iterations)
        elif provider_type == "openai_compatible":
            from core.providers.openai_compatible_provider import OpenAICompatibleProvider
            return OpenAICompatibleProvider(provider_config, self.registry, self.logger, max_iterations)
        else:
            raise ValueError(f"Unknown provider type: '{provider_type}'")

    def refresh_settings(self):
        """Call after the Settings/Skills dialogs save changes."""
        reload_settings()
        self.registry = _build_registry()

    def process_message(self, user_prompt: str, save_to_memory: bool = True) -> str:
        self.logger.log("user_message", {"text": user_prompt})
        recent_context = load_chat(self.chat_id)
        system_instruction = SYSTEM_INSTRUCTION_TEMPLATE.format(context=recent_context)
        provider = self.get_provider_instance()
        try:
            response_text = provider.run(user_prompt, system_instruction)
        except Exception as e:
            self.logger.log("error", {"message": str(e)})
            raise RuntimeError(f"Error from provider '{self.config_label()}': {e}")
        if save_to_memory:
            save_chat(self.chat_id, user_prompt, response_text)
        return response_text

    def config_label(self) -> str:
        return get_active_provider().get("label", "unknown provider")
