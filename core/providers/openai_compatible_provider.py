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


class OpenAICompatibleProvider(BaseProvider):
    def __init__(self, provider_config, tool_registry, logger, max_iterations=8):
        super().__init__(provider_config, tool_registry, logger, max_iterations)
        self.client = OpenAI(
            base_url=provider_config.get("base_url") or None,
            api_key=resolve_api_key(provider_config) or "not-needed",
        )
        self.model = provider_config.get("model", "")

    def run(self, user_prompt: str, system_instruction: str) -> str:
        messages = [
            {"role": "system", "content": system_instruction},
            {"role": "user", "content": user_prompt},
        ]
        tools_schema = self.tool_registry.as_openai_schema()

        self.logger.log("model_request", {"provider": self.config.get("id"), "model": self.model, "prompt": user_prompt})

        for _ in range(self.max_iterations):
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=tools_schema or None,
                temperature=0.2,
            )
            message = response.choices[0].message

            if not message.tool_calls:
                final_text = message.content or "Action completed."
                self.logger.log("final_answer", {"text": final_text})
                return final_text

            messages.append(message)
            for tool_call in message.tool_calls:
                fn_name = tool_call.function.name
                try:
                    fn_args = json.loads(tool_call.function.arguments) if tool_call.function.arguments else {}
                except Exception:
                    fn_args = {}

                self.logger.log("tool_call", {"name": fn_name, "arguments": fn_args})
                result = self.tool_registry.call(fn_name, fn_args)
                self.logger.log("tool_result", {"name": fn_name, "result": result})

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": str(result),
                })

        return "Reached the maximum number of reasoning steps without a final answer."
