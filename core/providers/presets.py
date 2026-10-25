"""Provider presets offered from Settings → Providers → "Add preset".

Presets are templates only: they are never injected silently into
``settings.json``. Choosing one in the dialog copies its fields into a new
provider entry that the user can edit and save.
"""

from __future__ import annotations

from typing import Any

PROVIDER_PRESETS: list[dict[str, Any]] = [
    {"id": "openrouter", "label": "OpenRouter", "type": "openai_compatible",
     "base_url": "https://openrouter.ai/api/v1", "env_var": "OPENROUTER_API_KEY",
     "model": "openrouter/auto"},
    {"id": "opencode", "label": "OpenCode", "type": "openai_compatible",
     "base_url": "https://opencode.ai/inference/openai/v1", "env_var": "OPENCODE_API_KEY",
     "model": "deepseek-v4.1-flash-free"},
    {"id": "claude", "label": "Anthropic Claude", "type": "anthropic",
     "base_url": "", "env_var": "ANTHROPIC_API_KEY", "model": "claude-sonnet-4-6"},
    {"id": "grok", "label": "xAI Grok", "type": "openai_compatible",
     "base_url": "https://api.x.ai/v1", "env_var": "XAI_API_KEY", "model": "grok-4.7"},
    {"id": "ollama", "label": "Ollama", "type": "openai_compatible",
     "base_url": "http://localhost:11434/v1", "env_var": "OLLAMA_API_KEY",
     "model": "qwen3:4b", "local": True},
    {"id": "colibri_models", "label": "Colibri Models", "type": "openai_compatible",
     "base_url": "http://127.0.0.1:8000/v1", "env_var": "COLIBRI_MODELS_API_KEY",
     "model": "qwen3.6-colibri", "local": True},
    {"id": "lm_studio", "label": "LM Studio", "type": "openai_compatible",
     "base_url": "http://localhost:1234/v1", "env_var": "LM_STUDIO_API_KEY",
     "model": "local-model", "local": True},
    {"id": "gemini", "label": "Google Gemini", "type": "gemini",
     "base_url": "", "env_var": "GEMINI_API_KEY", "model": "gemini-2.5-flash"},
    {"id": "opencode_anthropic", "label": "OpenCode (Anthropic)", "type": "anthropic",
     "base_url": "https://opencode.ai/inference/anthropic", "env_var": "OPENCODE_API_KEY",
     "model": "claude-sonnet-4-6"},
]


def get_preset(preset_id: str) -> dict[str, Any] | None:
    for preset in PROVIDER_PRESETS:
        if preset["id"] == preset_id:
            return dict(preset)
    return None


def provider_from_preset(preset: dict[str, Any], existing_ids: set[str]) -> dict[str, Any]:
    """Build a provider config dict from a preset with a unique id."""
    base_id = preset["id"]
    new_id, n = base_id, 2
    while new_id in existing_ids:
        new_id, n = f"{base_id}_{n}", n + 1
    return {
        "id": new_id,
        "label": preset["label"],
        "type": preset["type"],
        "base_url": preset.get("base_url", ""),
        "api_key": "not-needed" if preset.get("local") else "",
        "model": preset.get("model", ""),
        "env_var": preset.get("env_var", ""),
    }
