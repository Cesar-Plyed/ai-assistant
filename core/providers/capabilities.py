"""Capability flags per provider/model.

Flags: ``supports_tools``, ``supports_vision``, ``supports_streaming``,
``context_window`` and ``tool_mode`` (``native`` | ``text``). Values come from
heuristics on the provider type and model id, and can always be overridden by
keys of the same name in the provider's settings entry.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

_VISION_HINTS = re.compile(
    r"(gpt-4o|gpt-4\.1|gpt-5|o4|vision|llava|\bvl\b|-vl|qwen.*vl|gemma-?3|pixtral|"
    r"llama-?3\.2-(11|90)b|llama-?4|minicpm-v|moondream|bakllava|grok-(2-vision|4)|"
    r"claude|gemini|mistral-(small|medium)-3|internvl)",
    re.IGNORECASE,
)
_NO_TOOLS_HINTS = re.compile(r"(embed|whisper|tts|moderation|reranker|dall-?e)", re.IGNORECASE)


@dataclass(frozen=True)
class ProviderCapabilities:
    supports_tools: bool = True
    supports_vision: bool = False
    supports_streaming: bool = True
    context_window: int = 8192
    tool_mode: str = "native"   # "native" | "text"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _context_window(provider_type: str, model: str) -> int:
    m = model.lower()
    if provider_type == "anthropic" or "claude" in m:
        return 200_000
    if provider_type == "gemini" or "gemini" in m:
        return 1_000_000
    for marker, size in (("gpt-4.1", 1_000_000), ("gpt-4o", 128_000), ("gpt-5", 400_000),
                         ("grok", 256_000), ("llama-3.1", 128_000), ("qwen3", 32_768),
                         ("qwen2.5", 32_768), ("deepseek", 128_000)):
        if marker in m:
            return size
    return 8192


def get_capabilities(provider: dict[str, Any]) -> ProviderCapabilities:
    ptype = str(provider.get("type") or "openai_compatible")
    model = str(provider.get("model") or "")
    supports_tools = not _NO_TOOLS_HINTS.search(model)
    caps = ProviderCapabilities(
        supports_tools=supports_tools,
        supports_vision=bool(_VISION_HINTS.search(model)) or ptype in ("anthropic", "gemini"),
        supports_streaming=True,
        context_window=_context_window(ptype, model),
        tool_mode="native" if supports_tools else "text",
    )
    overrides: dict[str, Any] = {}
    for key in ("supports_tools", "supports_vision", "supports_streaming"):
        if isinstance(provider.get(key), bool):
            overrides[key] = provider[key]
    if isinstance(provider.get("context_window"), int) and provider["context_window"] > 0:
        overrides["context_window"] = provider["context_window"]
    if provider.get("tool_mode") in ("native", "text"):
        overrides["tool_mode"] = provider["tool_mode"]
    return ProviderCapabilities(**{**caps.as_dict(), **overrides})
