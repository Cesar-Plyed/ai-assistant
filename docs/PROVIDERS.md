# Providers

A provider is one backend the assistant can talk to. Every entry in
`settings.json → providers` has the same shape; only `type` changes how it is
called. `config.DEFAULT_SETTINGS` ships five entries and the app starts on
`lm_studio_local`:

| Default id | Type | Default model | Purpose |
|---|---|---|---|
| `lm_studio_local` | `openai_compatible` | `local-model` | Local LM Studio server on `:1234`. |
| `ollama_local` | `openai_compatible` | `qwen2.5:3b` | Local Ollama through its `/v1` endpoint. |
| `cloud_openai_compatible` | `openai_compatible` | `gpt-4o-mini` | Any hosted OpenAI-compatible API. |
| `cloud_gemini` | `gemini` | `gemini-2.5-flash` | Native Google Gemini SDK. |
| `cloud_anthropic` | `anthropic` | `claude-sonnet-4-5` | Native Anthropic Messages API. |

These are editable defaults, not fixed choices. Add, remove or reorder entries
in **Settings → Providers**; the active one is selected from the top bar or with
`/model`.

## Provider types

`core/providers/__init__.py::PROVIDER_SPECS` is the single catalogue used by the
factory, the Settings type list and the connection probe:

| Type | Class | Wire protocol |
|---|---|---|
| `openai_compatible` | `OpenAICompatibleProvider` | OpenAI chat-completions (`openai` SDK). Covers LM Studio, Ollama, OpenRouter, Groq, OpenAI and most local servers. |
| `gemini` | `GeminiProvider` | Native `google-genai` chats and function declarations. |
| `anthropic` | `AnthropicProvider` | Native Messages API with `tool_use` / `tool_result` blocks. |

SDKs are imported lazily when a provider of that type is created, so a local
OpenAI-compatible setup never imports `anthropic` or `google-genai`. A missing
optional SDK only breaks the provider that needs it.

## Presets

**Settings → Providers → Add preset** copies a template into a new editable
entry. Presets are never injected silently into `settings.json`; a second copy
gets a suffixed id (`openrouter_2`, …).

| Preset | Type | Base URL | Env var | Suggested model |
|---|---|---|---|---|
| OpenRouter | `openai_compatible` | `https://openrouter.ai/api/v1` | `OPENROUTER_API_KEY` | `openrouter/auto` |
| OpenCode | `openai_compatible` | `https://opencode.ai/inference/openai/v1` | `OPENCODE_API_KEY` | `deepseek-v4.1-flash-free` |
| Anthropic Claude | `anthropic` | Anthropic API | `ANTHROPIC_API_KEY` | `claude-sonnet-4-6` |
| xAI Grok | `openai_compatible` | `https://api.x.ai/v1` | `XAI_API_KEY` | `grok-4.7` |
| Ollama | `openai_compatible` | `http://localhost:11434/v1` | `OLLAMA_API_KEY` | `qwen3:4b` |
| Colibri Models | `openai_compatible` | `http://127.0.0.1:8000/v1` | `COLIBRI_MODELS_API_KEY` | `qwen3.6-colibri` |
| LM Studio | `openai_compatible` | `http://localhost:1234/v1` | `LM_STUDIO_API_KEY` | `local-model` |
| Google Gemini | `gemini` | — | `GEMINI_API_KEY` | `gemini-2.5-flash` |
| OpenCode (Anthropic) | `anthropic` | `https://opencode.ai/inference/anthropic` | `OPENCODE_API_KEY` | `claude-sonnet-4-6` |

Local presets (`ollama`, `colibri_models`, `lm_studio`) are created with
`api_key: "not-needed"`. Model ids in presets are suggestions: model names
change often, so use **Refresh models** to ask the provider what it actually
serves.

## Model list

`core/providers/model_catalog.py`:

- `STATIC_MODELS` supplies instant suggestions per provider type.
- `fetch_models()` asks the backend live: OpenAI-compatible `GET /models`,
  Ollama `GET /api/tags` (falling back to `/models`), Gemini and Anthropic via
  their SDK `models.list()`.
- Results are cached in `data/model_cache.json` with a 6-hour TTL. The button
  forces a refresh; a stale cache is not served when a live request fails.
- The model field is an editable combo with a case-insensitive "contains"
  completer, so an id missing from the list can still be typed.

## Capabilities

`core/providers/capabilities.py::get_capabilities()` derives:

| Flag | Heuristic |
|---|---|
| `supports_tools` | False for model ids matching `embed`, `whisper`, `tts`, `moderation`, `reranker` or `dall-e`. |
| `supports_vision` | True for `anthropic` and `gemini`, or model ids matching the vision hint regex (`gpt-4o`, `llava`, `qwen*vl`, `claude`, `gemini`, `grok-4`, `llama-3.2-11b/90b`, …). |
| `supports_streaming` | Always true; the current loops use non-streaming calls. |
| `context_window` | Heuristic by family: Claude 200 k, Gemini 1 M, GPT-4.1 1 M, GPT-4o 128 k, GPT-5 400 k, Grok 256 k, Qwen 32 768, DeepSeek 128 k, otherwise 8 192. |
| `tool_mode` | `native` when tools are supported, otherwise `text`. |

Override any of them per provider by adding a key of the same name to the
provider entry in `settings.json` (booleans for the three `supports_*` flags,
a positive integer for `context_window`, `native`/`text` for `tool_mode`).

Without vision, image attachments are **not** sent as pixels: the model receives
the numbered text manifest and the UI shows an `attachments_skipped` toast.

## API keys

`config.resolve_api_key()` checks, in order:

1. `<PROVIDER_ID>_API_KEY`, with the provider `id` uppercased (for example
   `LM_STUDIO_LOCAL_API_KEY` or `CLOUD_GEMINI_API_KEY`).
2. The provider entry's `env_var` (for example `OPENROUTER_API_KEY`).
3. The vendor fallback: `ANTHROPIC_API_KEY` for Anthropic,
   `GEMINI_API_KEY` for Gemini.
4. The `api_key` stored in `settings.json`.

Environment variables always win, which keeps real keys out of the repository.
The Settings dialog can probe a provider with **Test connection**
(`check_provider_connection()` calls the SDK's cheapest authenticated list
operation).

## Adding a provider type

Implement a `BaseProvider` subclass with `run(user_prompt, system_instruction,
history=None, attachments=None)`, then add one `ProviderSpec` entry (label,
factory, probe) to `core/providers/__init__.py`. The Settings dialog, factory
and connection probe pick it up automatically; `AIEngine` needs no change.
