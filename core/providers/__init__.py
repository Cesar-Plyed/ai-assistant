"""Provider factory and user-facing provider type catalogue.

Concrete providers import their SDK lazily, so selecting an OpenAI-compatible
provider never imports google-genai or anthropic. The same catalogue drives the
Settings dialog (type list and connection probe), so adding a provider type is
one entry here instead of edits in three modules.
"""

from dataclasses import dataclass
from typing import Any, Callable

from config import resolve_api_key
from core.providers.base_provider import BaseProvider


def _create_openai(provider_config, tool_registry, logger, max_iterations,
                   tool_profile="compact", tool_choice="auto",
                   parallel_tool_calls=True, temperature=0.2, max_tokens=None):
    from core.providers.openai_compatible_provider import OpenAICompatibleProvider

    return OpenAICompatibleProvider(
        provider_config, tool_registry, logger, max_iterations,
        tool_profile=tool_profile, tool_choice=tool_choice,
        parallel_tool_calls=parallel_tool_calls,
        temperature=temperature, max_tokens=max_tokens,
    )


def _create_gemini(provider_config, tool_registry, logger, max_iterations,
                   tool_profile="compact", tool_choice="auto",
                   parallel_tool_calls=True, temperature=0.2, max_tokens=None):
    from core.providers.gemini_provider import GeminiProvider

    return GeminiProvider(
        provider_config, tool_registry, logger, max_iterations,
        tool_profile=tool_profile, tool_choice=tool_choice,
        parallel_tool_calls=parallel_tool_calls,
        temperature=temperature, max_tokens=max_tokens,
    )


def _create_anthropic(provider_config, tool_registry, logger, max_iterations,
                      tool_profile="compact", tool_choice="auto",
                      parallel_tool_calls=True, temperature=0.2, max_tokens=None):
    from core.providers.anthropic_provider import AnthropicProvider

    return AnthropicProvider(
        provider_config, tool_registry, logger, max_iterations,
        tool_profile=tool_profile, tool_choice=tool_choice,
        parallel_tool_calls=parallel_tool_calls,
        temperature=temperature, max_tokens=max_tokens,
    )


def _probe_openai(provider_config: dict[str, Any]) -> None:
    from openai import OpenAI

    client = OpenAI(
        base_url=provider_config.get("base_url") or None,
        api_key=resolve_api_key(provider_config) or "not-needed",
    )
    client.models.list()


def _probe_gemini(provider_config: dict[str, Any]) -> None:
    from google import genai

    api_key = resolve_api_key(provider_config, "GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("No API key set.")
    genai.Client(api_key=api_key).models.list()


def _probe_anthropic(provider_config: dict[str, Any]) -> None:
    import anthropic

    api_key = resolve_api_key(provider_config, "ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("No API key set.")
    anthropic.Anthropic(api_key=api_key).models.list()


@dataclass(frozen=True)
class ProviderSpec:
    label: str
    factory: Callable[..., BaseProvider]
    probe: Callable[[dict[str, Any]], None]


PROVIDER_SPECS: dict[str, ProviderSpec] = {
    "openai_compatible": ProviderSpec(
        label="OpenAI-compatible (LM Studio / Ollama / cloud API)",
        factory=_create_openai,
        probe=_probe_openai,
    ),
    "gemini": ProviderSpec(
        label="Google Gemini (native)",
        factory=_create_gemini,
        probe=_probe_gemini,
    ),
    "anthropic": ProviderSpec(
        label="Anthropic Claude (native)",
        factory=_create_anthropic,
        probe=_probe_anthropic,
    ),
}

PROVIDER_TYPES = [(provider_type, spec.label) for provider_type, spec in PROVIDER_SPECS.items()]


def create_provider(
    provider_config: dict[str, Any],
    tool_registry,
    logger,
    max_iterations: int = 8,
    tool_profile: str = "compact",
    tool_choice: str = "auto",
    parallel_tool_calls: bool = True,
    temperature: float = 0.2,
    max_tokens: int | None = None,
) -> BaseProvider:
    provider_type = provider_config.get("type")
    spec = PROVIDER_SPECS.get(provider_type)
    if spec is None:
        raise ValueError(f"Unknown provider type: '{provider_type}'")
    return spec.factory(
        provider_config,
        tool_registry,
        logger,
        max_iterations,
        tool_profile=tool_profile,
        tool_choice=tool_choice,
        parallel_tool_calls=parallel_tool_calls,
        temperature=temperature,
        max_tokens=max_tokens,
    )


def check_provider_connection(provider_config: dict[str, Any]) -> None:
    """Probe a provider with its SDK's cheapest authenticated call."""
    provider_type = provider_config.get("type")
    spec = PROVIDER_SPECS.get(provider_type)
    if spec is None:
        raise ValueError(f"Unknown provider type: '{provider_type}'")
    spec.probe(provider_config)
