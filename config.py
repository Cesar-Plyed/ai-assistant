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
import shutil
import sys
from pathlib import Path
from typing import Any

APP_NAME = "AI Desktop Assistant"
SOURCE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


def _user_data_dir() -> Path:
    """Per-user writable data directory (used by packaged builds)."""
    if sys.platform == "win32":
        root = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        root = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return root / APP_NAME


def _resolve_base_dir() -> Path:
    """Where settings, chats, logs, workspace and skills live.

    ``AI_ASSISTANT_HOME`` wins (tests / portable installs); a frozen
    (PyInstaller) build uses the per-user data dir because its install folder
    is read-only; a source checkout keeps everything next to the code.
    """
    override = os.environ.get("AI_ASSISTANT_HOME")
    if override:
        return Path(override).expanduser().resolve()
    if getattr(sys, "frozen", False):
        return _user_data_dir()
    return Path(__file__).resolve().parent


BASE_DIR = _resolve_base_dir()
BASE_DIR.mkdir(parents=True, exist_ok=True)
SETTINGS_PATH = BASE_DIR / "settings.json"
DEV_LOG_DIR = BASE_DIR / "logs"
WORKSPACE_DIR = BASE_DIR / "workspace"
UPLOADS_DIR = WORKSPACE_DIR / "uploads"
SKILLS_DIR = BASE_DIR / "skills"

for _dir in (DEV_LOG_DIR, WORKSPACE_DIR, UPLOADS_DIR, SKILLS_DIR):
    _dir.mkdir(parents=True, exist_ok=True)

# Seed bundled example skills into a relocated skills dir on first run.
_BUNDLED_SKILLS = SOURCE_DIR / "skills"
if _BUNDLED_SKILLS.is_dir() and _BUNDLED_SKILLS.resolve() != SKILLS_DIR.resolve():
    for _skill in _BUNDLED_SKILLS.iterdir():
        _target = SKILLS_DIR / _skill.name
        if _skill.is_dir() and not _target.exists():
            shutil.copytree(_skill, _target, ignore=shutil.ignore_patterns("__pycache__"))

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
        {
            "id": "cloud_anthropic",
            "label": "Anthropic Claude (cloud)",
            "type": "anthropic",
            "base_url": "",
            "api_key": "",
            "model": "claude-sonnet-4-5",
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
    "max_tool_result_chars": 20000,
    "mcp_servers": [],
    "mcp_call_timeout": 60,
    "theme": "dark",                       # dark | light | system
    "reduce_motion": False,
    # ── Tool profiles ──────────────────────────────────────────────────
    # full: every registered tool. compact: filesystem+browser+system only
    # (default for 4B models). read-only: read-only tools only.
    "tool_profile": "compact",
    # tool_choice: auto | required | off
    "tool_choice": "auto",
    "parallel_tool_calls": True,
    "temperature": 0.2,
    "max_tokens": 4096,
}


# Tool groups used by tool profiles. Each group lists tool name prefixes
# (or exact names) that belong to it. Skill-provided tools fall under "skills",
# MCP tools under "mcp".
TOOL_GROUPS: dict[str, list[str]] = {
    "filesystem": [
        "list_project_files", "read_text_file", "write_text_file",
        "import_uploaded_file",
    ],
    "browser": [
        "browser_goto", "browser_read_page", "browser_list_interactive_elements",
        "browser_click", "browser_fill", "browser_set_checkbox",
        "browser_select_option", "browser_press_key", "browser_move_mouse",
        "browser_click_at", "browser_scroll", "browser_type_text", "browser_close",
    ],
    "system": [
        "run_console_command", "list_installed_applications",
        "open_application", "get_hardware_status",
    ],
    "mouse": [
        "take_screenshot", "move_mouse", "click_mouse", "type_text", "press_key",
    ],
}

# Which groups each profile enables. "skills" and "mcp" are always added
# by the engine when skills/MCP are enabled; they are listed here for
# completeness but are not profile-controlled.
PROFILE_GROUPS: dict[str, list[str]] = {
    "full": ["filesystem", "browser", "system", "mouse", "skills", "mcp"],
    "compact": ["filesystem", "browser", "system", "skills", "mcp"],
    "read-only": [
        "list_project_files", "read_text_file", "load_skill", "read_skill_reference",
        "browser_read_page", "browser_list_interactive_elements",
        "get_hardware_status",
    ],
}


# Extra tool names allowed in the "read-only" profile (set by the skills manager
# from enabled read-only skills' ``allowed-tools``).
READ_ONLY_EXTRA_TOOLS: set[str] = set()


def tools_for_profile(profile: str, all_tool_names: list[str]) -> list[str]:
    """Return the subset of ``all_tool_names`` allowed by ``profile``.

    Unknown profiles fall back to ``full``. Skill and MCP tools are always
    included when their names appear in ``all_tool_names`` (the engine
    decides which of those are enabled). Core tools whose name doesn't match
    any known group prefix are always included (they may be custom or
    skill-provided tools registered directly).
    """
    if profile == "read-only":
        allowed_names = set(PROFILE_GROUPS["read-only"]) | READ_ONLY_EXTRA_TOOLS
        return [name for name in all_tool_names if name in allowed_names]
    groups = PROFILE_GROUPS.get(profile, PROFILE_GROUPS["full"])
    group_set = set(groups)
    # Build a map: tool name -> set of groups it belongs to (for known core tools).
    name_to_groups: dict[str, set[str]] = {}
    for group, prefixes in TOOL_GROUPS.items():
        for prefix in prefixes:
            for name in all_tool_names:
                if name == prefix or name.startswith(prefix + "__"):
                    name_to_groups.setdefault(name, set()).add(group)

    allowed: set[str] = set()
    for name in all_tool_names:
        groups_for_name = name_to_groups.get(name)
        if not groups_for_name:
            # Unknown/custom tool (skill, MCP, or directly registered): always allow.
            allowed.add(name)
            continue
        # Include if any of its groups are enabled by the profile.
        if groups_for_name & group_set:
            allowed.add(name)
        # Skills and MCP tools are always included.
        if name.startswith("mcp__") or name.startswith("skill__"):
            allowed.add(name)
    return [name for name in all_tool_names if name in allowed]


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


def resolve_api_key(provider: dict[str, Any], vendor_env_var: str | None = None) -> str:
    """
    Resolve the API key for a provider. An environment variable named
    "<PROVIDER_ID>_API_KEY" (uppercased) always overrides the value saved
    in settings.json, so users can keep real keys out of the JSON file.

    ``vendor_env_var`` lets a cloud provider accept its vendor-standard
    variable (e.g. ``ANTHROPIC_API_KEY``) as a fallback without putting
    provider-type knowledge in this module.
    """
    env_var = f"{provider.get('id', '').upper()}_API_KEY"
    key = os.getenv(env_var)
    if key:
        return key

    # Preset-declared variable (e.g. OPENROUTER_API_KEY) set in the provider entry.
    custom_var = provider.get("env_var")
    if custom_var:
        key = os.getenv(custom_var)
        if key:
            return key

    if vendor_env_var:
        key = os.getenv(vendor_env_var)
        if key:
            return key

    return provider.get("api_key", "")


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
