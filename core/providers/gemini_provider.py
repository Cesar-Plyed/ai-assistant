"""Native Google Gemini provider, using the google-genai SDK directly (rather
than its OpenAI-compatibility layer) so function calling matches Gemini's
native format."""

from typing import Any

from config import resolve_api_key
from core.providers.base_provider import BaseProvider
from core.providers import multimodal


def _to_plain(value: Any) -> Any:
    """Recursively turn SDK wrappers (MapComposite, Struct, ...) into plain
    Python dicts/lists so tools receive ordinary JSON-shaped arguments."""
    if value is None or isinstance(value, (str, bytes, bool, int, float)):
        return value
    if isinstance(value, dict):
        return {key: _to_plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_to_plain(item) for item in value]

    items = getattr(value, "items", None)
    if callable(items):
        try:
            return {key: _to_plain(item) for key, item in items()}
        except Exception:
            pass

    # Older SDK versions model Struct as a pydantic object without .items().
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            return _to_plain(model_dump())
        except Exception:
            pass

    return value


def _response_text(response) -> str:
    """Return the response text, tolerating responses that have no text part."""
    if response is None:
        return ""
    try:
        text = response.text
    except ValueError:
        return ""
    return text if isinstance(text, str) else ""


class GeminiProvider(BaseProvider):
    def __init__(self, provider_config, tool_registry, logger, max_iterations=8,
                 tool_profile="compact", tool_choice="auto",
                 parallel_tool_calls=True, temperature=0.2, max_tokens=None):
        super().__init__(
            provider_config, tool_registry, logger, max_iterations,
            tool_profile=tool_profile, tool_choice=tool_choice,
            parallel_tool_calls=parallel_tool_calls,
            temperature=temperature, max_tokens=max_tokens,
        )
        from google import genai

        api_key = resolve_api_key(provider_config, "GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("No API key configured for the Gemini provider. Set it in Settings.")
        self.client = genai.Client(api_key=api_key)
        self.model = provider_config.get("model", "gemini-2.5-flash")

    def run(self, user_prompt: str, system_instruction: str,
            history: list[dict] | None = None, attachments: list[dict] | None = None) -> str:
        from google.genai import types

        self.logger.log("model_request", {"provider": self.config.get("id"), "model": self.model, "prompt": user_prompt})

        # Replay stored history as real user/model turns (it used to be dropped).
        gemini_history = []
        for msg in multimodal.clean_history(history):
            if msg["role"] not in ("user", "assistant") or not msg["content"]:
                continue
            gemini_history.append(types.Content(
                role="user" if msg["role"] == "user" else "model",
                parts=[types.Part.from_text(text=str(msg["content"]))],
            ))

        config_kwargs: dict[str, Any] = {
            "system_instruction": system_instruction,
            "tools": self._filtered_gemini_schema(),
            "temperature": self.temperature,
        }
        if self.max_tokens:
            config_kwargs["max_output_tokens"] = int(self.max_tokens)
        chat = self.client.chats.create(
            model=self.model,
            config=types.GenerateContentConfig(**config_kwargs),
            history=gemini_history or None,
        )

        self._check_cancelled()
        tool_names: list[str] = []
        pending: Any = multimodal.gemini_parts(user_prompt, attachments)

        for _ in range(self.max_iterations):
            self._check_cancelled()
            response = chat.send_message(pending)
            function_calls = getattr(response, "function_calls", None) or []

            finish_reason = None
            candidates = getattr(response, "candidates", None) or []
            if candidates:
                finish_reason = getattr(candidates[0], "finish_reason", None)
            usage = getattr(response, "usage_metadata", None)
            usage_dict = None
            if usage is not None:
                usage_dict = {
                    "prompt_token_count": getattr(usage, "prompt_token_count", None),
                    "candidates_token_count": getattr(usage, "candidates_token_count", None),
                    "total_token_count": getattr(usage, "total_token_count", None),
                }
                usage_dict = {k: v for k, v in usage_dict.items() if v is not None}
            self._log_model_response(response, finish_reason=finish_reason, usage=usage_dict)

            if function_calls:
                # Gemini expects one user turn containing a function_response
                # part for every call, so collect them all before sending.
                parts = []
                for call in function_calls:
                    name = getattr(call, "name", None)
                    if not name:
                        continue
                    arguments = _to_plain(getattr(call, "args", None))
                    if not isinstance(arguments, dict):
                        arguments = {}
                    tool_names.append(name)

                    # Anti-repeat guard.
                    if self._is_repeat(name, arguments):
                        result = self.report_tool_error(
                            name, arguments,
                            f"Repeated call to '{name}' with the same arguments; stop repeating and answer.",
                        )
                        parts.append(
                            types.Part.from_function_response(
                                name=name,
                                response={"result": result.content},
                            )
                        )
                        continue

                    result = self.execute_tool(name, arguments)
                    parts.append(
                        types.Part.from_function_response(
                            name=name,
                            response={"result": result.content},
                        )
                    )

                if not parts:
                    break

                pending = parts
                continue

            text = _response_text(response)
            recovered = self.run_text_tool_calls(text)
            if recovered is not None:
                # Some models write the call as JSON text instead of using the
                # native tool channel. Run it and feed the results back.
                tool_names.extend(recovered.tool_names)
                pending = recovered.payload
                continue

            return self.finalize(tool_names, text)

        return self.finalize_exhausted(tool_names)
