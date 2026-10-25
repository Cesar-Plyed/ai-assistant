# Changelog

## [1.0.0]
- Theme system (Dark / Light / System) from one global stylesheet (`ui/theme.py`).
- `/ @ ;` completion popup with fuzzy filter, icons and badges; `/model /settings /skills /new /export /mcp`.
- MCP wired into the window (background connect, `;server.tool {json}`), toasts for tool effects.
- Attachments: tray with `#n` numbering, paste/drag & drop, multimodal OpenAI/Anthropic/Gemini.
- Skills 2.0 (`SKILL.md`, on-demand loading, validation, safe install, legacy migration).
- Settings in six tabs; model combo with threaded refresh, Ollama `/api/tags`, TTL cache.
- Provider capability flags; Gemini now receives chat history; Anthropic `required` → `any`, base URL.
- Provider presets (Settings → Providers → Add preset) with per-preset API-key env vars.
- Hardware monitor shows CPU / RAM / GPU only (disks removed).
- `AI_ASSISTANT_HOME`, per-user data dir for packaged builds, PyInstaller spec, Windows installer, macOS DMG and release workflow.
- Python pinned to 3.13 (`.python-version`, `requires-python <3.14`); `uv.lock` committed.
- `[dev]` extra added; Pillow, PyYAML, beautifulsoup4, requests declared.
- 185-test suite; CI runs on Linux, Windows and macOS.

## [Unreleased]


## [0.2.0]
- PySide6 + uv migration, MCP MVP, toasts, native Anthropic provider, tool profiles.
