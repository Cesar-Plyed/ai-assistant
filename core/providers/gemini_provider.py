"""Native Google Gemini provider, using the google-genai SDK directly (rather
than its OpenAI-compatibility layer) so function calling matches Gemini's
native format."""

from config import resolve_api_key
from core.providers.base_provider import BaseProvider


class GeminiProvider(BaseProvider):
    def __init__(self, provider_config, tool_registry, logger, max_iterations=8):
        super().__init__(provider_config, tool_registry, logger, max_iterations)
        from google import genai

        api_key = resolve_api_key(provider_config)
        if not api_key:
            raise RuntimeError("No API key configured for the Gemini provider. Set it in Settings.")
        self.client = genai.Client(api_key=api_key)
        self.model = provider_config.get("model", "gemini-2.5-flash")

    def run(self, user_prompt: str, system_instruction: str) -> str:
        from google.genai import types

        self.logger.log("model_request", {"provider": self.config.get("id"), "model": self.model, "prompt": user_prompt})

        chat = self.client.chats.create(
            model=self.model,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                tools=self.tool_registry.as_gemini_declarations(),
                temperature=0.2,
            ),
        )

        response = chat.send_message(user_prompt)
        iterations = 0

        while response.function_calls and iterations < self.max_iterations:
            for call in response.function_calls:
                fn_name = call.name
                fn_args = dict(call.args) if call.args else {}

                self.logger.log("tool_call", {"name": fn_name, "arguments": fn_args})
                result = self.tool_registry.call(fn_name, fn_args)
                self.logger.log("tool_result", {"name": fn_name, "result": result})

                response = chat.send_message(
                    types.Part.from_function_response(name=fn_name, response={"result": result})
                )
            iterations += 1

        final_text = response.text if response.text else "Action completed."
        self.logger.log("final_answer", {"text": final_text})
        return final_text
