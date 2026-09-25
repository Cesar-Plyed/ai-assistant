# config.py
"""
Central configuration for the assistant.

Settings are stored in a user-editable JSON file (settings.json) instead of
being hard-coded, so the app can be reconfigured from the Settings dialog
without touching source code. API keys can also be supplied via environment
variables, which always take priority over the file (safer for sharing the
project / committing it to version control).
"""

import json
import os
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
SETTINGS_PATH = BASE_DIR / "settings.json"
LOGS_DIR = BASE_DIR / "logs_chats"
DEV_LOG_DIR = BASE_DIR / "logs"
WORKSPACE_DIR = BASE_DIR / "workspace"
UPLOADS_DIR = WORKSPACE_DIR / "uploads"
SKILLS_DIR = BASE_DIR / "skills"

for _dir in (LOGS_DIR, DEV_LOG_DIR, WORKSPACE_DIR, UPLOADS_DIR, SKILLS_DIR):
    _dir.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Default settings. "providers" is a list so the user can register as many
# backends as they want (several LM Studio instances, Ollama, a cloud API,
# etc.) and switch between them from the UI.
# ---------------------------------------------------------------------------
DEFAULT_SETTINGS: dict[str, Any] = {
    "active_provider": "lm_studio_local",
    "providers": [
        {
            "id": "lm_studio_local",
            "label": "LM Studio (local)",
            "type": "openai_compatible",
            "base_url": "http://localhost:1234/v1",
            "api_key": "not-needed",
            "model": "local-model",
        },
        {
            "id": "ollama_local",
            "label": "Ollama (local)",
            "type": "openai_compatible",
            "base_url": "http://localhost:11434/v1",
            "api_key": "ollama",
            "model": "qwen2.5:3b",
        },
        {
            "id": "cloud_openai_compatible",
            "label": "Cloud API (OpenAI-compatible)",
            "type": "openai_compatible",
            "base_url": "https://api.openai.com/v1",
            "api_key": "",
            "model": "gpt-4o-mini",
        },
        {
            "id": "cloud_gemini",
            "label": "Google Gemini (cloud)",
            "type": "gemini",
            "base_url": "",
            "api_key": "",
            "model": "gemini-2.5-flash",
        },
    ],
    "dev_mode": False,
    "enable_mouse_control": False,
    "enable_browser_page_reading": True,
    "enable_browser_automation": True,
    "browser_mode": "attach",              # "attach" (debug browser) or "launch"
    "browser_autostart": True,             # start the debug browser if it isn't running
    "browser_debug_port": 9222,
    "browser_debug_profile": "~/.job-agent-profile",
    "require_submit_confirmation": True,
    "enabled_skills": [],
    "max_agent_iterations": 8,
    "theme": "dark",
}


def _deep_merge_defaults(base: dict, override: dict) -> dict:
    """Fill in any keys missing from `override` using `base`, recursively for dicts."""
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge_defaults(result[key], value)
        else:
            result[key] = value
    return result


def load_settings() -> dict[str, Any]:
    if SETTINGS_PATH.exists():
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                user_settings = json.load(f)
            merged = _deep_merge_defaults(DEFAULT_SETTINGS, user_settings)
        except Exception:
            merged = dict(DEFAULT_SETTINGS)
    else:
        merged = dict(DEFAULT_SETTINGS)
        save_settings(merged)
    return merged


def save_settings(settings: dict[str, Any]) -> None:
    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)


def resolve_api_key(provider: dict[str, Any]) -> str:
    """
    Resolve the API key for a provider. An environment variable named
    "<PROVIDER_ID>_API_KEY" (uppercased) always overrides the value saved
    in settings.json, so users can keep real keys out of the JSON file.
    """
    env_var = f"{provider.get('id', '').upper()}_API_KEY"
    return os.getenv(env_var) or provider.get("api_key", "")


# Singleton-style settings object used across the app. Call reload_settings()
# after the Settings dialog saves changes.
SETTINGS: dict[str, Any] = load_settings()


def reload_settings() -> dict[str, Any]:
    global SETTINGS
    SETTINGS = load_settings()
    return SETTINGS


def get_active_provider() -> dict[str, Any]:
    active_id = SETTINGS.get("active_provider")
    for provider in SETTINGS.get("providers", []):
        if provider["id"] == active_id:
            return provider
    # Fall back to the first provider if the active one was removed.
    providers = SETTINGS.get("providers", [])
    return providers[0] if providers else {}
