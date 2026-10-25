"""Tests for the provider factory and provider type catalogue."""

from types import SimpleNamespace

import anthropic
import pytest

from core.providers import PROVIDER_TYPES, check_provider_connection, create_provider
from core.providers.anthropic_provider import AnthropicProvider
from core.tools import ToolRegistry
from tests.fakes import FakeLogger
import config


def test_factory_returns_anthropic_provider(monkeypatch):
    monkeypatch.setattr(anthropic, "Anthropic", lambda **kwargs: SimpleNamespace())

    provider = create_provider(
        {"id": "x", "type": "anthropic", "api_key": "k", "model": "m"},
        ToolRegistry(),
        FakeLogger(),
    )

    assert isinstance(provider, AnthropicProvider)
    assert provider.model == "m"


def test_factory_rejects_unknown_type():
    with pytest.raises(ValueError):
        create_provider(
            {"id": "x", "type": "nope", "api_key": "k"},
            ToolRegistry(),
            FakeLogger(),
        )


def test_provider_types_includes_native_providers():
    provider_types = {provider_type for provider_type, _label in PROVIDER_TYPES}

    assert {"openai_compatible", "gemini", "anthropic"} <= provider_types


def test_connection_check_rejects_unknown_type():
    with pytest.raises(ValueError):
        check_provider_connection({"type": "nope"})


def test_vendor_api_key_is_used_as_a_fallback(monkeypatch):
    monkeypatch.delenv("CLOUD_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "vendor-key")

    key = config.resolve_api_key(
        {"id": "cloud_anthropic", "type": "anthropic", "api_key": ""},
        "ANTHROPIC_API_KEY",
    )

    assert key == "vendor-key"
