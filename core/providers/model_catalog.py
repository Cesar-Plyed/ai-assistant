"""Model catalogues for the Settings dialog.

``STATIC_MODELS`` provides useful completion values without a network call.
``fetch_models`` asks a provider for its live model list and always raises
``RuntimeError`` with a short, user-facing message on failure, so the dialog
can show it directly without leaking tracebacks.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
import time
from pathlib import Path
from typing import Any

import config

# Keep these lists short but current. The Settings dialog shows them as
# autocomplete suggestions; users can always type a model id that is missing.
STATIC_MODELS: dict[str, list[str]] = {
    "openai_compatible": [
        "gpt-4o-mini",
        "gpt-4.1-mini",
        "gpt-4.1",
        "qwen2.5:3b",
        "qwen2.5:7b",
        "llama-3.1-8b-instruct",
        "mistral-nemo",
    ],
    "gemini": [
        "gemini-2.5-flash",
        "gemini-2.5-pro",
        "gemini-2.5-flash-lite",
        "gemini-2.0-flash",
        "gemini-2.0-flash-lite",
        "gemini-1.5-pro",
        "gemini-1.5-flash",
    ],
    "anthropic": [
        "claude-sonnet-4-5",
        "claude-opus-4-1",
        "claude-haiku-4-5",
        "claude-3-7-sonnet-latest",
        "claude-3-5-haiku-latest",
        "claude-3-opus-latest",
    ],
}


def static_models(provider_type: str) -> list[str]:
    """Return a copy of the built-in model list for ``provider_type``."""
    return list(STATIC_MODELS.get(str(provider_type or ""), []))


def fetch_models(provider: dict[str, Any], timeout: float = 10.0) -> list[str]:
    """Fetch the provider's live model list.

    Raises ``RuntimeError`` with a short, readable message on any failure.
    """
    provider_type = str(provider.get("type") or "")
    if provider_type == "openai_compatible":
        if is_ollama(provider):
            try:
                return _fetch_ollama_models(provider, timeout)
            except RuntimeError:
                pass  # fall back to the OpenAI-compatible /models endpoint
        return _fetch_openai_models(provider, timeout)
    if provider_type == "gemini":
        return _fetch_gemini_models(provider, timeout)
    if provider_type == "anthropic":
        return _fetch_anthropic_models(provider, timeout)
    raise RuntimeError(f"Unsupported provider type: '{provider_type or 'unknown'}'.")


def is_ollama(provider: dict[str, Any]) -> bool:
    ident = f"{provider.get('id', '')} {provider.get('base_url', '')}".lower()
    return "ollama" in ident or ":11434" in ident


def _api_key(provider: dict[str, Any], vendor_env: str | None = None) -> str:
    """Key from env var / settings (``resolve_api_key``), so env-only keys work."""
    return str(config.resolve_api_key(provider, vendor_env) or "").strip()


def _http_get_json(url: str, headers: dict[str, str], timeout: float) -> Any:
    try:
        request = urllib.request.Request(url, headers=headers, method="GET")
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Model list request failed (HTTP {exc.code}).") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not reach {url}: {getattr(exc, 'reason', exc)}") from exc
    except OSError as exc:
        raise RuntimeError(f"Could not reach {url}: {exc}") from exc
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("The provider returned an invalid model list.") from exc


def _fetch_ollama_models(provider: dict[str, Any], timeout: float) -> list[str]:
    """Ollama native listing: ``GET /api/tags`` on the server root."""
    base_url = str(provider.get("base_url") or "").strip().rstrip("/")
    if not base_url:
        raise RuntimeError("Set a base URL before fetching models.")
    root = base_url[:-3] if base_url.endswith("/v1") else base_url
    payload = _http_get_json(f"{root}/api/tags", {"Accept": "application/json"}, timeout)
    entries = payload.get("models") if isinstance(payload, dict) else None
    names = []
    if isinstance(entries, list):
        for entry in entries:
            if isinstance(entry, dict):
                name = entry.get("name") or entry.get("model")
                if isinstance(name, str):
                    names.append(name.strip())
    names = _unique(names)
    if not names:
        raise RuntimeError("Ollama returned no models.")
    return names


# ── Cache (data/model_cache.json) ────────────────────────────────────────
CACHE_TTL_SECONDS = 6 * 3600


def _cache_path() -> Path:
    return config.BASE_DIR / "data" / "model_cache.json"


def _cache_key(provider: dict[str, Any]) -> str:
    return "|".join(str(provider.get(k) or "") for k in ("id", "type", "base_url"))


def _load_cache() -> dict[str, Any]:
    try:
        data = json.loads(_cache_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def cached_models(provider: dict[str, Any], ttl: float = CACHE_TTL_SECONDS) -> list[str] | None:
    """Return cached model ids if present and younger than ``ttl`` seconds."""
    entry = _load_cache().get(_cache_key(provider))
    if not isinstance(entry, dict):
        return None
    try:
        age = time.time() - float(entry.get("fetched_at", 0))
    except (TypeError, ValueError):
        return None
    models = entry.get("models")
    if age > ttl or not isinstance(models, list) or not models:
        return None
    return [str(m) for m in models]


def store_cached_models(provider: dict[str, Any], models: list[str]) -> None:
    cache = _load_cache()
    cache[_cache_key(provider)] = {"fetched_at": time.time(), "models": list(models)}
    try:
        path = _cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass


def list_models(provider: dict[str, Any], force_refresh: bool = False,
                timeout: float = 10.0, ttl: float = CACHE_TTL_SECONDS) -> list[str]:
    """Models for ``provider``: TTL cache first, live fetch otherwise.

    Raises ``RuntimeError`` (short user-facing message) when the live fetch
    fails and no cached list exists; a stale-but-present cache is not served
    silently on failure so errors stay visible.
    """
    if not force_refresh:
        hit = cached_models(provider, ttl)
        if hit:
            return hit
    models = fetch_models(provider, timeout)
    store_cached_models(provider, models)
    return models


def _unique(values: list[str]) -> list[str]:
    """Drop blanks and duplicates while preserving the provider's order."""
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _fetch_openai_models(provider: dict[str, Any], timeout: float) -> list[str]:
    base_url = str(provider.get("base_url") or "").strip()
    if not base_url:
        raise RuntimeError("Set a base URL before fetching models.")

    url = f"{base_url.rstrip('/')}/models"
    headers = {"Accept": "application/json"}
    api_key = _api_key(provider)
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        request = urllib.request.Request(url, headers=headers, method="GET")
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Model list request failed (HTTP {exc.code}).") from exc
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        raise RuntimeError(f"Could not reach {url}: {reason}") from exc
    except OSError as exc:
        raise RuntimeError(f"Could not reach {url}: {exc}") from exc
    except ValueError as exc:
        raise RuntimeError(f"Invalid base URL: {base_url}") from exc
    except Exception as exc:
        raise RuntimeError(f"Could not fetch models from {url}: {exc}") from exc

    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("The provider returned an invalid model list.") from exc

    entries = payload.get("data") if isinstance(payload, dict) else None
    models: list[str] = []
    if isinstance(entries, list):
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            model_id = entry.get("id")
            if isinstance(model_id, str):
                models.append(model_id.strip())

    models = _unique(models)
    if not models:
        raise RuntimeError("The provider returned no models.")
    return models


def _fetch_gemini_models(provider: dict[str, Any], timeout: float) -> list[str]:
    api_key = _api_key(provider, "GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("Set an API key before fetching Gemini models.")

    try:
        from google import genai
    except ImportError as exc:
        raise RuntimeError("google-genai is not installed.") from exc

    try:
        try:
            client = genai.Client(
                api_key=api_key,
                http_options={"timeout": int(timeout * 1000)},
            )
        except TypeError:
            # Older SDK versions (and simple test doubles) only take api_key.
            client = genai.Client(api_key=api_key)
        raw_models = list(client.models.list())
    except Exception as exc:
        raise RuntimeError(f"Could not fetch Gemini models: {exc}") from exc

    models: list[str] = []
    for model in raw_models:
        name = str(getattr(model, "name", "") or "").strip()
        if name.startswith("models/"):
            name = name[len("models/"):]
        models.append(name)

    models = _unique(models)
    if not models:
        raise RuntimeError("Gemini returned no models.")
    return models


def _fetch_anthropic_models(provider: dict[str, Any], timeout: float) -> list[str]:
    api_key = _api_key(provider, "ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("Set an API key before fetching Anthropic models.")

    try:
        import anthropic
    except ImportError as exc:
        raise RuntimeError("anthropic is not installed.") from exc

    try:
        try:
            kwargs: dict[str, Any] = {"api_key": api_key, "timeout": timeout}
            if provider.get("base_url"):
                kwargs["base_url"] = str(provider["base_url"])
            client = anthropic.Anthropic(**kwargs)
        except TypeError:
            # Simple test doubles may only accept the api_key argument.
            client = anthropic.Anthropic(api_key=api_key)
        raw_models = list(client.models.list())
    except Exception as exc:
        raise RuntimeError(f"Could not fetch Anthropic models: {exc}") from exc

    models = [str(getattr(model, "id", "") or "").strip() for model in raw_models]
    models = _unique(models)
    if not models:
        raise RuntimeError("Anthropic returned no models.")
    return models
