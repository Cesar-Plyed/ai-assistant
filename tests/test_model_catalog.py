"""Tests for the static/live model catalogue."""

import json
import urllib.error
import urllib.request

import pytest

from core.providers import model_catalog


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_static_models_known_types_have_sensible_sizes():
    for provider_type in ("openai_compatible", "gemini", "anthropic"):
        models = model_catalog.static_models(provider_type)
        assert 5 <= len(models) <= 10
        assert models == model_catalog.STATIC_MODELS[provider_type]


def test_static_models_unknown_type_is_empty():
    assert model_catalog.static_models("does-not-exist") == []
    assert model_catalog.static_models("") == []


def test_fetch_openai_models_sends_auth_header(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["headers"] = {
            key.lower(): value for key, value in request.header_items()
        }
        captured["timeout"] = timeout
        return FakeResponse({"data": [{"id": "a"}, {"id": "b"}]})

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    provider = {
        "type": "openai_compatible",
        "base_url": "http://localhost:1234/v1/",
        "api_key": "secret",
    }
    assert model_catalog.fetch_models(provider) == ["a", "b"]
    assert captured["url"] == "http://localhost:1234/v1/models"
    assert captured["headers"]["authorization"] == "Bearer secret"
    assert captured["timeout"] == 10.0


def test_fetch_openai_models_without_api_key_omits_auth_header(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["headers"] = {
            key.lower(): value for key, value in request.header_items()
        }
        return FakeResponse({"data": [{"id": "local-model"}]})

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    provider = {
        "type": "openai_compatible",
        "base_url": "http://localhost:11434/v1",
        "api_key": "",
    }
    assert model_catalog.fetch_models(provider) == ["local-model"]
    assert "authorization" not in captured["headers"]


def test_fetch_openai_models_requires_base_url():
    with pytest.raises(RuntimeError, match="base URL"):
        model_catalog.fetch_models(
            {"type": "openai_compatible", "base_url": "", "api_key": "x"}
        )


def test_fetch_openai_models_wraps_http_errors(monkeypatch):
    def fake_urlopen(request, timeout=None):
        raise urllib.error.HTTPError(
            request.full_url, 500, "Server Error", None, None
        )

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(RuntimeError, match="HTTP 500"):
        model_catalog.fetch_models(
            {
                "type": "openai_compatible",
                "base_url": "http://localhost:1234/v1",
                "api_key": "secret",
            }
        )


def test_fetch_openai_models_wraps_invalid_url(monkeypatch):
    def fake_urlopen(request, timeout=None):
        raise ValueError("unknown url type")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(RuntimeError, match="Invalid base URL"):
        model_catalog.fetch_models(
            {
                "type": "openai_compatible",
                "base_url": "not-a-url",
                "api_key": "",
            }
        )


def test_fetch_openai_models_empty_result_raises(monkeypatch):
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda request, timeout=None: FakeResponse({"data": []}),
    )

    with pytest.raises(RuntimeError, match="no models"):
        model_catalog.fetch_models(
            {
                "type": "openai_compatible",
                "base_url": "http://localhost:1234/v1",
                "api_key": "secret",
            }
        )


def test_fetch_models_unknown_type_raises():
    with pytest.raises(RuntimeError, match="Unsupported provider type"):
        model_catalog.fetch_models({"type": "unknown"})
