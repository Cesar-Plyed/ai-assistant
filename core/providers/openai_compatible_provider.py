"""
Provider for any backend that speaks the OpenAI chat-completions protocol:
LM Studio, Ollama (via its /v1 compatibility endpoint), and most cloud APIs,
paid or free (OpenAI itself, OpenRouter, Groq, Together, etc.).

Only base_url, api_key, and model differ between them, so a single class
covers all of them.
"""

import json

from openai import OpenAI

from config import resolve_api_key
from core.providers.base_provider import BaseProvider
from core.providers import multimodal


class OpenAICompatibleProvider(BaseProvider):
    def __init__(self, provider_config, tool_registry, logger, max_iterations=8,
                 tool_profile="compact", tool_choice="auto",
                 parallel_tool_calls=True, temperature=0.2, max_tokens=None):
        super().__init__(
            provider_config, tool_registry, logger, max_iterations,
            tool_profile=tool_profile, tool_choice=tool_choice,
            parallel_tool_calls=parallel_tool_calls,
            temperature=temperature, max_tokens=max_tokens,
        )
        self.client = OpenAI(
            base_url=provider_config.get("base_url") or None,
            api_key=resolve_api_key(provider_config) or "not-needed",
        )
        self.model = provider_config.get("model", "")

    def _build_messages(self, system_instruction, history, user_prompt, attachments=None):
        """Build the message list: system + history (user/assistant) + current user."""
        messages = [{"role": "system", "content": system_instruction}]
        messages.extend(multimodal.clean_history(history))
        messages.append({
            "role": "user",
            "content": multimodal.openai_user_content(user_prompt, attachments),
        })
        return messages

    def _tool_choice_param(self):
        """Map tool_choice setting to the OpenAI API value."""
        choice = self.tool_choice
        if choice == "off":
            return "none"
        if choice == "required":
            return "required"
        return "auto"

    def run(self, user_prompt: str, system_instruction: str,
            history: list[dict] | None = None, attachments: list[dict] | None = None) -> str:
        history = history or []
        messages = self._build_messages(system_instruction, history, user_prompt, attachments)
        tools_schema = self._filtered_schema()

        self.logger.log("model_request", {"provider": self.config.get("id"), "model": self.model, "prompt": user_prompt})

        tool_names: list[str] = []
        for _ in range(self.max_iterations):
            self._check_cancelled()
            create_kwargs = {
                "model": self.model,
                "messages": messages,
                "tools": tools_schema or None,
                "tool_choice": self._tool_choice_param() if tools_schema else "none",
                "temperature": self.temperature,
            }
            if self.max_tokens:
                create_kwargs["max_tokens"] = self.max_tokens
            response = self.client.chat.completions.create(**create_kwargs)
            if not getattr(response, "choices", None):
                raise RuntimeError("The provider returned an empty response (no choices).")
            message = response.choices[0].message
            tool_calls = message.tool_calls

            finish_reason = getattr(response.choices[0], "finish_reason", None)
            usage = getattr(response, "usage", None)
            usage_dict = None
            if usage is not None:
                usage_dict = {
                    "prompt_tokens": getattr(usage, "prompt_tokens", None),
                    "completion_tokens": getattr(usage, "completion_tokens", None),
                    "total_tokens": getattr(usage, "total_tokens", None),
                }
                usage_dict = {k: v for k, v in usage_dict.items() if v is not None}
            self._log_model_response(response, finish_reason=finish_reason, usage=usage_dict)

            if not tool_calls:
                recovered = self.run_text_tool_calls(message.content or "")
                if recovered is not None:
                    # Some local models write the call as JSON text instead of
                    # using the native tool channel. Run it and feed the results
                    # back in the same turn so the loop can continue.
                    messages.append({"role": "assistant", "content": message.content})
                    messages.append({"role": "user", "content": recovered.payload})
                    tool_names.extend(recovered.tool_names)
                    continue

                final_text = message.content or getattr(message, "refusal", None) or ""
                return self.finalize(tool_names, final_text)

            messages.append(self._serialize_message(message))
            for tool_call in tool_calls:
                fn_name = tool_call.function.name
                raw_args = tool_call.function.arguments
                try:
                    fn_args = json.loads(raw_args) if raw_args else {}
                    if not isinstance(fn_args, dict):
                        raise ValueError(f"expected a JSON object, got {type(fn_args).__name__}")
                except Exception as e:
                    # Never run a tool with empty/garbage arguments: report the
                    # problem back to the model and let it retry the call.
                    error_text = f"Invalid JSON arguments for tool '{fn_name}': {e}"
                    result = self.report_tool_error(fn_name, raw_args, error_text)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": result.content,
                    })
                    continue

                # Anti-repeat guard: same tool + same args as the last call.
                if self._is_repeat(fn_name, fn_args):
                    result = self.report_tool_error(
                        fn_name, fn_args,
                        f"Repeated call to '{fn_name}' with the same arguments; stop repeating and answer.",
                    )
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": result.content,
                    })
                    continue

                result = self.execute_tool(fn_name, fn_args)
                tool_names.append(fn_name)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result.content,
                })

        # The model used tools but produced no final text answer.
        # Summarize what was done so the user sees a response in chat.
        return self.finalize_exhausted(tool_names)

    @staticmethod
    def _serialize_message(message) -> dict:
        """Return a plain-dict copy of an assistant message so it can be appended
        to the request history (SDK message objects are not subscriptable)."""
        model_dump = getattr(message, "model_dump", None)
        if callable(model_dump):
            return model_dump(exclude_none=True)
        return {
            "role": "assistant",
            "content": getattr(message, "content", None),
            "tool_calls": [
                {
                    "id": tool_call.id,
                    "type": "function",
                    "function": {
                        "name": tool_call.function.name,
                        "arguments": tool_call.function.arguments,
                    },
                }
                for tool_call in (getattr(message, "tool_calls", None) or [])
            ],
        }
