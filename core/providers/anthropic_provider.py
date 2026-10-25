"""Native Anthropic Claude provider, using the Messages API directly so tool
use follows Claude's native content-block format."""

from typing import Any

from config import resolve_api_key
from core.providers.base_provider import BaseProvider
from core.providers import multimodal

DEFAULT_MODEL = "claude-sonnet-4-6"
DEFAULT_MAX_TOKENS = 4096


class AnthropicProvider(BaseProvider):
    def __init__(self, provider_config, tool_registry, logger, max_iterations=8,
                 tool_profile="compact", tool_choice="auto",
                 parallel_tool_calls=True, temperature=0.2, max_tokens=None):
        super().__init__(
            provider_config, tool_registry, logger, max_iterations,
            tool_profile=tool_profile, tool_choice=tool_choice,
            parallel_tool_calls=parallel_tool_calls,
            temperature=temperature, max_tokens=max_tokens,
        )
        import anthropic

        api_key = resolve_api_key(provider_config, "ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("No API key configured for the Anthropic provider. Set it in Settings.")
        client_kwargs: dict[str, Any] = {"api_key": api_key}
        if provider_config.get("base_url"):
            client_kwargs["base_url"] = str(provider_config["base_url"])
        self.client = anthropic.Anthropic(**client_kwargs)
        self.model = provider_config.get("model", DEFAULT_MODEL)
        self.max_tokens = self._resolve_max_tokens(max_tokens or provider_config.get("max_tokens"))

    @staticmethod
    def _resolve_max_tokens(value: Any) -> int:
        try:
            max_tokens = int(value or DEFAULT_MAX_TOKENS)
        except (TypeError, ValueError):
            max_tokens = DEFAULT_MAX_TOKENS
        return max(1, max_tokens)

    @staticmethod
    def _block_to_dict(block) -> dict[str, Any]:
        """Return a plain-dict copy of a content block for the request history."""
        model_dump = getattr(block, "model_dump", None)
        if callable(model_dump):
            return model_dump(exclude_none=True)
        data = {}
        for key in ("type", "text", "id", "name", "input"):
            value = getattr(block, key, None)
            if value is not None:
                data[key] = value
        return data

    def _tool_choice_param(self) -> dict[str, Any] | None:
        """Map tool_choice setting to Anthropic's tool_choice dict."""
        choice = self.tool_choice
        if choice == "off":
            return {"type": "none"}
        if choice == "required":
            return {"type": "any"}
        return {"type": "auto"}

    def run(self, user_prompt: str, system_instruction: str,
            history: list[dict] | None = None, attachments: list[dict] | None = None) -> str:
        history = history or []
        messages: list[dict[str, Any]] = [
            m for m in multimodal.clean_history(history) if m["role"] in ("user", "assistant")
        ]
        messages.append({
            "role": "user",
            "content": multimodal.anthropic_user_content(user_prompt, attachments),
        })
        tools = self._filtered_anthropic_schema()

        self.logger.log("model_request", {"provider": self.config.get("id"), "model": self.model, "prompt": user_prompt})

        tool_names: list[str] = []

        for _ in range(self.max_iterations):
            self._check_cancelled()

            request: dict[str, Any] = {
                "model": self.model,
                "system": system_instruction,
                "messages": messages,
                "max_tokens": self.max_tokens,
            }
            if tools:
                request["tools"] = tools
                request["tool_choice"] = self._tool_choice_param()

            response = self.client.messages.create(**request)
            content = list(response.content or [])

            finish_reason = getattr(response, "stop_reason", None)
            usage = getattr(response, "usage", None)
            usage_dict = None
            if usage is not None:
                usage_dict = {
                    "input_tokens": getattr(usage, "input_tokens", None),
                    "output_tokens": getattr(usage, "output_tokens", None),
                }
                usage_dict = {k: v for k, v in usage_dict.items() if v is not None}
            self._log_model_response(response, finish_reason=finish_reason, usage=usage_dict)

            text = "".join(block.text for block in content if block.type == "text")

            # Capture reasoning_content if present (Claude 3.7+ / 4.x).
            reasoning = "".join(
                getattr(block, "reasoning_content", "") or ""
                for block in content
                if getattr(block, "type", "") == "thinking"
            )
            if reasoning:
                self.logger.log("reasoning_content", {"text": reasoning})

            tool_uses = [block for block in content if block.type == "tool_use"]
            if not tool_uses:
                recovered = self.run_text_tool_calls(text)
                if recovered is not None:
                    messages.append({"role": "assistant", "content": text})
                    messages.append({"role": "user", "content": recovered.payload})
                    tool_names.extend(recovered.tool_names)
                    continue

                stop_reason = getattr(response, "stop_reason", None)
                if not text and stop_reason in ("refusal", "model_context_window_exceeded"):
                    text = f"The model stopped without answering ({stop_reason})."
                return self.finalize(tool_names, text)

            messages.append(
                {
                    "role": "assistant",
                    "content": [self._block_to_dict(block) for block in content],
                }
            )

            tool_results = []
            for tool_use in tool_uses:
                tool_names.append(tool_use.name)
                result = self.execute_tool(tool_use.name, dict(tool_use.input or {}))
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_use.id,
                        "content": result.content or "(no output)",
                        "is_error": result.failed,
                    }
                )

            messages.append({"role": "user", "content": tool_results})

        return self.finalize_exhausted(tool_names)
