import config
from core.providers import PROVIDER_SPECS
from core.providers.presets import PROVIDER_PRESETS, get_preset, provider_from_preset


def test_presets_use_known_provider_types():
    for preset in PROVIDER_PRESETS:
        assert preset["type"] in PROVIDER_SPECS


def test_preset_ids_unique_and_complete():
    ids = [p["id"] for p in PROVIDER_PRESETS]
    assert len(ids) == len(set(ids)) == 9


def test_provider_from_preset_unique_id():
    preset = get_preset("ollama")
    first = provider_from_preset(preset, set())
    second = provider_from_preset(preset, {first["id"]})
    assert first["id"] == "ollama" and second["id"] == "ollama_2"
    assert first["base_url"] == "http://localhost:11434/v1"


def test_resolve_api_key_uses_preset_env_var(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    provider = provider_from_preset(get_preset("openrouter"), set())
    assert config.resolve_api_key(provider) == "sk-test"


def test_capabilities_heuristics_and_overrides():
    from core.providers.capabilities import get_capabilities

    claude = get_capabilities({"type": "anthropic", "model": "claude-sonnet-4-6"})
    assert claude.supports_vision and claude.context_window == 200_000
    local = get_capabilities({"type": "openai_compatible", "model": "qwen3:4b"})
    assert not local.supports_vision and local.supports_tools
    forced = get_capabilities({"type": "openai_compatible", "model": "qwen3:4b",
                               "supports_vision": True, "context_window": 4096})
    assert forced.supports_vision and forced.context_window == 4096
