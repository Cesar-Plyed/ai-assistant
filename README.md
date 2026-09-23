# README.md

```markdown
# AI Desktop Assistant

A cross-platform (Windows / Linux) PyQt6 desktop application that runs an LLM-powered
agent with **real tool access to your machine**. It can read and write files, run shell
commands, launch applications and browsers, monitor hardware, fetch web pages, and
(optionally) control the mouse and keyboard — all driven by a chat interface.

The assistant is **provider-agnostic**: it works with any OpenAI-compatible endpoint
(LM Studio, Ollama, OpenAI, OpenRouter, Groq, Together, …) and with native Google Gemini.

---

## Table of contents

- [Features](#features)
- [Architecture](#architecture)
- [Project layout](#project-layout)
- [Installation](#installation)
- [First run](#first-run)
- [Configuring providers](#configuring-providers)
- [How the agent loop works](#how-the-agent-loop-works)
- [Tools reference](#tools-reference)
- [Skills (plugins)](#skills-plugins)
- [Settings reference](#settings-reference)
- [UI overview](#ui-overview)
- [Dev Mode](#dev-mode)
- [Security notes](#security-notes)
- [Troubleshooting](#troubleshooting)
- [Extending the project](#extending-the-project)

---

## Features

- **Multi-provider** — register any number of OpenAI-compatible backends or Gemini
  accounts, switch between them from the top bar at any time.
- **Native function calling** — the OpenAI provider uses `tools=[...]`, the Gemini
  provider uses the native `google-genai` SDK (not its OpenAI shim) so tool calls
  match each API's real wire format.
- **Live tool execution** — the model can call tools mid-conversation; results are
  fed back until it produces a final answer (bounded by `max_agent_iterations`).
- **Dev Mode panel** — a color-coded live log of every model request, tool call,
  tool result, and final answer, also persisted to `logs/*.jsonl`.
- **Live hardware monitor** — CPU, RAM, disk, and NVIDIA GPU usage, refreshed every
  2 seconds, both as a UI widget and as a tool the model can call.
- **Chat history** — per-chat JSON persistence, sidebar with rename/delete,
  automatic chat titles derived from the first message.
- **Pluggable skills** — drop a folder under `skills/` with a manifest and a
  `register(registry)` entry point; enable it from the Skills dialog.
- **Non-intrusive launching** — apps and browsers are opened on a **secondary
  virtual desktop** so they don't steal focus from what you're doing.
- **No external assets** — icons are inline SVGs rendered to `QIcon` at runtime.
- **Safe by default** — mouse/keyboard control is off until you explicitly enable
  it, and every one of those tools re-checks the flag on each call.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                           MainWindow (PyQt6)                        │
│  provider combo · chat view · docks (History / Dev / Hardware)      │
└───────────────┬─────────────────────────────────────────────────────┘
                │  AIWorker (QThread)           TitleWorker (QThread)
                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                              AIEngine                               │
│  builds tool registry · selects provider · persists chat memory     │
└─────┬─────────────────────────┬─────────────────────────────────────┘
      │                         │
      ▼                         ▼
┌───────────────┐        ┌─────────────────────────────────────────────┐
│  Providers    │        │            ToolRegistry (singleton)         │
│  ─────────    │        │  system · filesystem · browser · mouse      │
│  OpenAICompat │        │  + dynamically-loaded skills                │
│  Gemini       │        │                                             │
└───────────────┘        └─────────────────────────────────────────────┘
                                     │
                                     ▼
                     ┌───────────────────────────────┐
                     │   OS / hardware / network     │
                     └───────────────────────────────┘
```

The **agent loop** lives in each provider's `run()` method. The engine doesn't
know about tool schemas or transport formats; it just hands the provider a prompt
and a system instruction, and gets back a final string.

---

## Project layout

```
.
├── main.py                       # entry point
├── config.py                     # settings + defaults + API-key resolution
├── requirements.txt
├── settings.json                 # created on first run
├── data/
│   └── chats/                    # per-chat JSON history
├── logs/                         # DevLogger JSONL files
├── workspace/
│   └── uploads/                  # files attached from the UI
├── skills/                       # pluggable skill folders
└── core/
    ├── ai_engine.py              # orchestrator
    ├── memory.py                 # chat persistence
    ├── logger.py                 # DevLogger (Qt signal + JSONL)
    ├── skills_manager.py         # skill discovery / install
    ├── desktop_manager.py        # virtual-desktop switching
    ├── hardware_monitor.py       # psutil + nvidia-smi
    ├── providers/
    │   ├── base_provider.py
    │   ├── openai_compatible_provider.py
    │   └── gemini_provider.py
    └── tools/
        ├── __init__.py           # REGISTRY
        ├── system_tools.py
        ├── filesystem_tools.py
        ├── browser_tools.py
        └── mouse_tools.py
└── ui/
    ├── main_window.py
    ├── chat_history_widget.py
    ├── dev_console.py
    ├── hardware_widget.py
    ├── settings_dialog.py
    ├── skills_dialog.py
    └── icons.py
```

---

## Installation

Requires **Python 3.10+** (uses `X | None` union syntax in tool signatures).

```bash
git clone <your-repo-url>
cd ai-desktop-assistant
python -m venv .venv
source .venv/bin/activate         # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### Optional system dependencies

These enable extra features and degrade gracefully if missing:

| Feature | Linux | Windows |
|---|---|---|
| Virtual desktop switching on non-KDE | `wmctrl` | built-in (pyautogui) |
| KDE Plasma desktop switching | `qdbus` or `xdotool` | — |
| GPU monitoring | `nvidia-smi` (NVIDIA driver) | same |
| Reading web pages | `requests`, `beautifulsoup4` | same (in requirements) |
| Mouse/keyboard control | `python3-xlib` (in requirements) | built-in |

---

## First run

```bash
python main.py
```

On first launch:

1. `settings.json` is created from `DEFAULT_SETTINGS` in `config.py`.
2. The default active provider is **LM Studio (local)** pointing at
   `http://localhost:1234/v1`. If you don't have LM Studio running, switch to
   another provider or set one up (see below).
3. The chat window opens with the message *"Ready. Active model: …"*.

---

## Configuring providers

Open **Settings → Preferences…**. On the left is a list of providers; on the
right is an editor form.

### Adding a provider

1. Click **Add** — a new row appears with sensible defaults.
2. Fill in the form:
   - **Label** — what you'll see in the top-bar dropdown.
   - **Type** — `OpenAI-compatible` or `Google Gemini (native)`.
   - **Base URL** — endpoint root (ignored for Gemini).
   - **API key** — leave blank for local servers that don't require one.
   - **Model** — the model id (`gpt-4o-mini`, `qwen2.5:3b`, `gemini-2.5-flash`, …).
3. Click **Save provider** (or just **Save and close** — the current form is
   always committed on close).
4. Click **Test connection** to verify before relying on it.

### Setting the active provider

Select a row and click **Set active**. The top-bar dropdown also switches the
active provider live, without reopening the dialog.

### Common endpoints

| Backend | Base URL | API key | Notes |
|---|---|---|---|
| LM Studio | `http://localhost:1234/v1` | anything | enable the local server in LM Studio |
| Ollama | `http://localhost:11434/v1` | `ollama` | needs the OpenAI-compat endpoint |
| OpenAI | `https://api.openai.com/v1` | your key | |
| OpenRouter | `https://openrouter.ai/api/v1` | your key | |
| Groq | `https://api.groq.com/openai/v1` | your key | |
| Together | `https://api.together.xyz/v1` | your key | |
| Google Gemini | *(blank)* | your key | type = `gemini` |

### Keeping keys out of `settings.json`

`config.resolve_api_key()` checks an environment variable first:

```bash
export LM_STUDIO_LOCAL_API_KEY="sk-..."      # Linux/macOS
setx LM_STUDIO_LOCAL_API_KEY "sk-..."        # Windows
```

The variable name is `<PROVIDER_ID>_API_KEY` (the provider's `id` field from
`settings.json`, uppercased). This always overrides whatever is stored in the
file, so you can share the project without leaking secrets.

---

## How the agent loop works

1. **UI** (`MainWindow._send_message`) appends your message to the view, spins up
   an `AIWorker(QThread)`, and calls `AIEngine.process_message(prompt)`.
2. **Engine** loads recent chat history, formats the system instruction, picks the
   active provider, and calls `provider.run(prompt, system_instruction)`.
3. **Provider** sends the prompt plus the tool schemas to the model.
4. If the response contains **tool calls**, each is executed via
   `ToolRegistry.call(name, args)`, logged to Dev Mode, and the result is sent
   back to the model as a tool/function response.
5. Steps 3–4 repeat until the model produces a plain text answer, or until
   `max_agent_iterations` is exhausted (default 8).
6. The engine persists `(user_prompt, response_text)` to `data/chats/<id>.json`
   and the worker emits the response back to the UI thread.

Every event also goes through `DevLogger.log(...)`, which:

- appends a JSON line to `logs/app_dev.jsonl`, and
- emits a Qt signal (`event_logged`) so `DevConsole` shows it live.

The signal is safe to emit from a worker thread — Qt queues it back to the GUI
thread automatically.

---

## Tools reference

Tools are exposed to the model as JSON Schema and can be disabled via Settings
or by not being in the enabled skills list. Current core tools:

### System (`core/tools/system_tools.py`)

| Tool | What it does |
|---|---|
| `run_console_command` | Runs a shell command (Bash on Linux, CMD/PowerShell on Windows) with a 30 s timeout. |
| `list_installed_applications` | Scans `.desktop` files (Linux) or the registry + Start Menu (Windows). |
| `open_application` | Launches an app by fuzzy name match on a secondary virtual desktop. |
| `get_hardware_status` | Human-readable CPU/RAM/disk/GPU snapshot. |

### Filesystem (`core/tools/filesystem_tools.py`)

| Tool | What it does |
|---|---|
| `list_project_files` | Lists a directory. |
| `read_text_file` | Reads a text file, truncated to `max_chars`. |
| `write_text_file` | Creates or overwrites a text file. |
| `import_uploaded_file` | Copies a user-attached file into `workspace/uploads/` with a timestamp prefix. |

### Browser (`core/tools/browser_tools.py`)

| Tool | What it does |
|---|---|
| `open_browser` | Launches Brave/Chrome/Firefox/Edge/Chromium (including Flatpak) to a URL or Google search. |
| `fetch_web_page_text` | Fetches a page and returns its title, visible text, and top 15 links. Gated by `enable_browser_page_reading`. |

### Mouse / keyboard (`core/tools/mouse_tools.py`)

All of these check `config.SETTINGS["enable_mouse_control"]` on every call, so
turning it off in Settings takes effect **immediately**, even mid-task.

| Tool | What it does |
|---|---|
| `take_screenshot` | Saves a PNG screenshot. |
| `move_mouse` | Moves the cursor to `(x, y)` over a given duration. |
| `click_mouse` | Clicks, optionally at `(x, y)`, left/right/middle. |
| `type_text` | Types text at the current focus. |
| `press_key` | Presses a single key (`enter`, `esc`, `tab`, …). |

---

## Skills (plugins)

A skill is a folder under `skills/<id>/` containing:

```
skills/
└── my_skill/
    ├── skill.json      # {"name": "...", "description": "...", "version": "1.0"}
    └── skill.py        # def register(registry) -> None: ...
```

`skill.py` must define a `register(registry)` function that calls
`registry.register(name=..., description=..., parameters={...}, func=...)` for
each tool it exposes. `parameters` uses JSON Schema (same shape as the core
tools).

### Installing

**Settings → Skills → Manage skills…**, then:

- **Install from folder…** — pick a directory containing `skill.json` + `skill.py`.
- **Install from .zip…** — same, but from a zip. A single nested folder is
  tolerated (`my_skill.zip` → `my_skill/skill.json` works).

After installing, tick the checkbox and click **Save and close**. The engine
rebuilds the registry so the new tools are live immediately.

### Loading rules

Skills are loaded only if their folder name appears in
`settings["enabled_skills"]`. Copying a folder into `skills/` does **not**
auto-enable it. Failed skill imports are printed to stdout (prefixed with
`[SkillsManager]`) and skipped rather than crashing the app.

---

## Settings reference

`settings.json` lives next to `config.py`. Defaults (from `config.DEFAULT_SETTINGS`):

| Key | Type | Default | Meaning |
|---|---|---|---|
| `active_provider` | string | `"lm_studio_local"` | id of the provider in `providers` currently in use |
| `providers` | list | see below | all registered providers |
| `dev_mode` | bool | `false` | show the Dev Mode dock at startup |
| `enable_mouse_control` | bool | `false` | master switch for `mouse_tools` |
| `enable_browser_page_reading` | bool | `true` | master switch for `fetch_web_page_text` |
| `enabled_skills` | list of strings | `[]` | skill folder names to load |
| `max_agent_iterations` | int | `8` | tool-call loop cap per user message |
| `theme` | string | `"dark"` | reserved |

Each entry in `providers`:

```json
{
  "id": "lm_studio_local",
  "label": "LM Studio (local)",
  "type": "openai_compatible",       // or "gemini"
  "base_url": "http://localhost:1234/v1",
  "api_key": "not-needed",
  "model": "local-model"
}
```

`config.load_settings()` deep-merges your file over `DEFAULT_SETTINGS`, so
upgrading the app never breaks an existing config — new keys get added
automatically.

---

## UI overview

```
┌─ Menu bar ─────────────────────────────────────────────────────────┐
│ Settings · Skills · View · Help                                    │
├─ Top bar ──────────────────────────────────────────────────────────┤
│ Active model: [ provider dropdown ▾ ]                              │
├─ Chat view (QTextBrowser, rendered Markdown) ──────────────────────┤
│  You: …                                                            │
│  Assistant: …                                                      │
├─ Input row ────────────────────────────────────────────────────────┤
│ [] [ type an instruction…                    ] [Send] [Cancel]   │
└────────────────────────────────────────────────────────────────────┘
   Left dock: Chat History    Right docks: Dev Console / Hardware Monitor
```

### Menu

- **Settings → Preferences…** — provider list, test connection, toggles.
- **Skills → Manage skills…** — enable/disable/install skills.
- **View** — show/hide the Chat History, Dev Mode, and Hardware Monitor docks.
- **Help → Commands** — quick cheat sheet.

### Slash commands (in the input field)

| Command | Effect |
|---|---|
| `/clear` | Clear the chat view (doesn't touch stored memory). |
| `/help` | Show the help message. |
| `/dev` | Toggle the Dev Mode panel. |

### Keyboard shortcuts

- **Enter** — send message.

---

## Dev Mode

Enable it from **View → Dev Mode panel**, **Settings**, or by running `/dev`.

The panel shows every event as a colored line:

| Event | Color | Meaning |
|---|---|---|
| `user_message` | blue | your prompt |
| `model_request` | light blue | the prompt sent to the model |
| `model_response` | teal | the model's reply |
| `tool_call` | yellow | a tool is being invoked, with arguments |
| `tool_result` | green | the tool's return value |
| `final_answer` | teal | the assistant's final text |
| `error` | red | an exception escaped the provider loop |

Every event is also appended to `logs/app_dev.jsonl` as JSON, so you can grep,
`jq`, or replay sessions later. `DevLogger.tail(n)` reads the last `n` events
from disk and is what populates the panel when it first opens.

---

## Security notes

This app is **powerful by design**. Read this section before running it with a
cloud model or on a machine with sensitive data.

### What the model can do by default

- **Run arbitrary shell commands** (`run_console_command`) with no confirmation
  dialog. This is always available. **This is the biggest risk.** A prompt
  injection in a web page returned by `fetch_web_page_text` could instruct the
  model to run malicious commands.
- **Read and write any file** the user account can access
  (`read_text_file`, `write_text_file`).
- **Open any installed application** and any URL in a browser.

### What is gated

- **Mouse/keyboard control** is off by default; the model can only use it after
  you tick *Enable mouse/keyboard control tools* in Settings.
- **Web page reading** can be disabled; if so, `fetch_web_page_text` returns a
  refusal string instead of fetching.

### Recommendations

1. If you use a **cloud model**, prefer running the assistant on a machine or
   user account where you're comfortable with the model executing shell
   commands.
2. If you want a hard guarantee, edit `system_tools.py` and remove
   `run_console_command` from `register()`, or wrap it behind a confirmation
   dialog.
3. Keep mouse/keyboard control **off** unless you're actively using it.
4. Use environment variables for API keys (`<PROVIDER_ID>_API_KEY`) so they
   don't end up in `settings.json` and version control.
5. Never commit `settings.json`, `data/chats/`, `logs/`, or `workspace/uploads/`
   if they may contain personal data. Add them to `.gitignore`.

Suggested `.gitignore`:

```
settings.json
data/
logs/
logs_chats/
workspace/
skills/*/__pycache__/
__pycache__/
*.pyc
.venv/
```

---

## Troubleshooting

### "No API key configured for the Gemini provider"

Open Settings, select the Gemini provider, paste your key into the *API key*
field, and click *Save provider*. Or export
`CLOUD_GEMINI_API_KEY` (the provider id, uppercased, with `_API_KEY`).

### The model never calls any tools

Check that the provider's `model` field names a model that supports function
calling. Some small local models do not. `qwen2.5:3b`, `llama3.1:8b`, and
`gpt-4o-mini` all do; a base completion model generally won't.

### "Reached the maximum number of reasoning steps…"

The model is looping on tool calls. Raise **Max reasoning steps per message** in
Settings, or simplify your request. If a specific tool keeps failing (e.g.
`run_console_command` returning an error), the model may retry it forever — check
the Dev Mode log for the tool result.

### A tool reports "Mouse/keyboard control is disabled"

Tick *Enable mouse/keyboard control tools* in Settings. The flag is read on every
call, so no restart is required.

### Chat history disappears after switching chats

Older versions of `memory.py` had a write race between the main response and the
title generator. The current version uses a re-entrant lock and atomic writes
(`tmp` + `Path.replace`). If you're upgrading, also make sure any stale
`data/chats/*.json.tmp` files are removed.

### Rename / delete silently does nothing

`memory.rename_chat` returns `False` when the target name already exists or
when the source file is missing; `memory.delete_chat` returns `False` when the
file can't be located. Both are reported by the UI with a warning dialog in the
current version. If you're on an older build, check the JSON id inside
`data/chats/<name>.json` — it may disagree with the filename and prevent lookup.

### The provider I added in Settings doesn't persist

The current Settings dialog commits the editor form on **Save and close**, not
only on **Save provider**. If you're on an older build, you must click *Save
provider* first.

### Hardware Monitor shows "GPU: no supported monitoring tool detected"

Only NVIDIA GPUs are queried (via `nvidia-smi`). AMD/Intel users see this
message by design; the widget and the `get_hardware_status` tool both handle it
gracefully.

### A skill won't load

- Check the folder contains **both** `skill.json` and `skill.py`.
- Check the skill's folder name is in `enabled_skills` in `settings.json` (the
  Skills dialog writes this for you).
- Look at stdout for a `[SkillsManager] Failed to load skill '…'` message with
  the actual exception.

---

## Extending the project

### Adding a new core tool

1. Create `core/tools/my_tools.py`.
2. Define a function that takes plain Python arguments and returns a string.
3. Define `register(registry)` that calls `registry.register(...)` for each tool.
4. Add an import + `my_tools.register(REGISTRY)` call in `core/ai_engine.py`
   inside `_build_registry()`.

```python
# core/tools/my_tools.py
def shout(text: str) -> str:
    return text.upper()

def register(registry) -> None:
    registry.register(
        name="shout",
        description="Return the given text in uppercase.",
        parameters={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        func=shout,
    )
```

```python
# core/ai_engine.py
from core.tools import my_tools
...
def _build_registry():
    filesystem_tools.register(REGISTRY)
    system_tools.register(REGISTRY)
    browser_tools.register(REGISTRY)
    mouse_tools.register(REGISTRY)
    my_tools.register(REGISTRY)          # <-- add this
    skills_manager.load_enabled_skills(REGISTRY)
    return REGISTRY
```

### Adding a new provider

1. Subclass `BaseProvider` and implement `run(self, user_prompt, system_instruction) -> str`.
2. In `run`, send the prompt + tool schemas to your backend, execute any tool
   calls via `self.tool_registry.call(name, args)`, and loop until you get a
   final text answer or hit `self.max_iterations`.
3. Register the new `type` in `SettingsDialog.PROVIDER_TYPES`.
4. Add a branch in `AIEngine.get_provider_instance()`.

### Changing the system instruction

The template lives in `core/ai_engine.py` as `SYSTEM_INSTRUCTION_TEMPLATE`. The
`{context}` placeholder is filled with the current chat history formatted by
`memory.load_chat`. Edit the template to change the assistant's persona, add
rules, or restrict tool usage.

---

## License

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)   

## Acknowledgements

- [PyQt6](https://pypi.org/project/PyQt6/) — GUI
- [openai](https://pypi.org/project/openai/) / [google-genai](https://pypi.org/project/google-genai/) — model SDKs
- [psutil](https://pypi.org/project/psutil/) — hardware monitoring
- [PyAutoGUI](https://pypi.org/project/PyAutoGUI/) — mouse/keyboard control
- [requests](https://pypi.org/project/requests/) + [BeautifulSoup](https://pypi.org/project/beautifulsoup4/) — page reading
- [Markdown](https://pypi.org/project/Markdown/) — chat rendering
```