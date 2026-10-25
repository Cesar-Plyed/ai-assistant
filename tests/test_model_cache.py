import json

import config
from core.providers import model_catalog


def test_list_models_uses_ttl_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    provider = {"id": "x", "type": "openai_compatible", "base_url": "http://h/v1"}
    calls = []

    def fake_fetch(p, timeout=10.0):
        calls.append(1)
        return ["a", "b"]

    monkeypatch.setattr(model_catalog, "fetch_models", fake_fetch)
    assert model_catalog.list_models(provider) == ["a", "b"]
    assert model_catalog.list_models(provider) == ["a", "b"]
    assert len(calls) == 1
    assert model_catalog.list_models(provider, force_refresh=True) == ["a", "b"]
    assert len(calls) == 2
    data = json.loads((tmp_path / "data" / "model_cache.json").read_text())
    assert next(iter(data.values()))["models"] == ["a", "b"]


def test_cache_expires(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    provider = {"id": "x", "type": "gemini"}
    model_catalog.store_cached_models(provider, ["m"])
    assert model_catalog.cached_models(provider, ttl=60) == ["m"]
    assert model_catalog.cached_models(provider, ttl=-1) is None


def test_ollama_uses_api_tags(monkeypatch):
    seen = {}

    def fake_get(url, headers, timeout):
        seen["url"] = url
        return {"models": [{"name": "qwen3:4b"}, {"name": "llama3:8b"}]}

    monkeypatch.setattr(model_catalog, "_http_get_json", fake_get)
    out = model_catalog.fetch_models({"id": "ollama", "type": "openai_compatible",
                                      "base_url": "http://localhost:11434/v1"})
    assert out == ["qwen3:4b", "llama3:8b"]
    assert seen["url"] == "http://localhost:11434/api/tags"
