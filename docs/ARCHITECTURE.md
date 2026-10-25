# Architecture

The assistant is a single-process PySide6 desktop application. A Qt window owns
the conversation, while every model request runs on a worker thread. The
`AIEngine` is the only orchestrator: it assembles context, picks the active
provider, runs one turn, and persists the result. Providers own the agent loop;
tools are shared through one registry, so a new tool is available to every
backend without provider changes.

## Design principles

| Principle | Consequence in the code |
|---|---|
| The engine is provider-agnostic | `AIEngine` never imports a transport SDK or a tool schema; it calls `create_provider(...).run(...)`. |
| One tool definition, three wire formats | `core/tools/__init__.py::ToolRegistry` exposes `as_openai_schema()`, `as_anthropic_schema()` and `as_gemini_declarations()`. |
| The GUI thread never blocks | `AIWorker`, `TitleWorker` and `MCPConnectWorker` are `QThread`s; `DevLogger` crosses back through queued Qt signals. |
| Settings are data, not code | `config.DEFAULT_SETTINGS` is deep-merged with `settings.json`; environment variables override API keys. |
| Context is loaded progressively | Skills ship a compact catalog; bodies load on `@skill` or `load_skill`. Attachments send a text manifest and only the current turn's pixels. |
| Persistence is metadata-first | Chats store attachment paths/hashes, never base64; model-ready images are regenerated from disk. |

---

## 1. System context

```mermaid
flowchart LR
    User([User]) -->|types, pastes, drops files| UI["PySide6 desktop UI"]
    UI -->|one turn| Engine["AIEngine"]
    Engine -->|chat-completions or native SDK| LLM["Model provider<br/>LM Studio · Ollama · OpenAI-compatible<br/>Gemini · Anthropic"]
    Engine -->|function calls| Tools["Tool layer<br/>filesystem · system · browser · mouse"]
    Engine -->|MCP protocol| MCPServers["External MCP servers"]
    Engine -->|skill instructions and code| Skills["Skill folders under skills/"]
    Tools --> OS["Operating system<br/>files · processes · desktop"]
    Tools --> Browser["Automation browser<br/>Playwright / CDP"]
    Engine -->|JSONL events| Logs[("logs/")]
    Engine -->|JSON chats| Chats[("data/chats/")]
    Engine -->|copies and derivatives| Uploads[("workspace/uploads/")]
    UI -->|settings| Settings[("settings.json")]
```

---

## 2. Layered architecture

```mermaid
flowchart TB
    subgraph Presentation["Presentation layer — ui/"]
        MW["MainWindow"]
        CHAT["QTextBrowser conversation"]
        COMPOSER["ChatInput composer"]
        TRAY["AttachmentTray"]
        HISTORY["ChatHistoryWidget"]
        DEV["DevConsole"]
        HARDWARE["HardwareWidget"]
        DIALOGS["SettingsDialog · SkillsDialog"]
        TOAST["ToastManager"]
    end

    subgraph Orchestration["Orchestration layer — core/"]
        ENGINE["AIEngine"]
        ATTACH["attachments.py"]
        SKILLMGR["skills_manager.py"]
        MEMORY["memory.py"]
        LOGGER["DevLogger"]
    end

    subgraph Agent["Agent runtime — core/providers/"]
        BASE["BaseProvider"]
        OAI["OpenAICompatibleProvider"]
        GEM["GeminiProvider"]
        ANT["AnthropicProvider"]
        TOOLTEXT["tool_text.py"]
        MULTI["multimodal.py"]
        CAPS["capabilities.py"]
    end

    subgraph Capabilities["Capability layer"]
        REG["ToolRegistry (REGISTRY)"]
        CORETOOLS["Core tools<br/>filesystem · system · browser · mouse"]
        SKILLTOOLS["Skill tools<br/>load_skill · read_skill_reference · skill.py"]
        MCPBRIDGE["MCP bridge<br/>mcp__server__tool"]
        MCPMGR["MCPManager"]
    end

    subgraph Platform["Platform and persistence"]
        CONFIG["config.py"]
        MEM["data/chats/*.json"]
        LOGS["logs/app_dev.jsonl"]
        WORK["workspace/uploads/"]
        SETTINGS["settings.json"]
        OS["OS · hardware · network"]
    end

    Presentation --> Orchestration
    Orchestration --> Agent
    Agent --> Capabilities
    Capabilities --> Platform
    CONFIG -.-> Presentation
    CONFIG -.-> Orchestration
    CONFIG -.-> Agent
    CONFIG -.-> Capabilities
```

Dependency rule: arrows point downward. `ui/` may import `core/`; `core/` never
imports `ui/`. `config.py` is imported by every layer and imports nothing from
the application. Provider SDKs (`openai`, `anthropic`, `google-genai`) are
imported lazily, so selecting one backend does not load the others.

---

## 3. Module map

| Area | Modules | Responsibility |
|---|---|---|
| Entry point | `main.py`, `config.py` | Create the `QApplication`, apply the theme, open `MainWindow`; own settings and base directories. |
| Engine | `core/ai_engine.py` | Build the registry, system prompt, skill/MCP context and attachment manifest; run one turn; persist it. |
| Providers | `core/providers/__init__.py`, `base_provider.py`, `openai_compatible_provider.py`, `gemini_provider.py`, `anthropic_provider.py` | Factory, shared tool execution/logging, and the per-provider agent loop. |
| Provider helpers | `capabilities.py`, `presets.py`, `model_catalog.py`, `multimodal.py`, `tool_text.py` | Vision/tool heuristics, settings presets, live model lists, multimodal payloads, JSON-text tool-call recovery. |
| Tools | `core/tools/__init__.py` (`REGISTRY`, `ToolResult`), `effects.py`, `filesystem_tools.py`, `system_tools.py`, `browser_automation.py`, `mouse_tools.py` | Tool schemas, validation, truncation, execution, toast metadata. |
| MCP | `core/mcp/manager.py`, `registry.py`, `mentions.py` | Async sessions in a daemon thread, registry bridge, `;server.tool` mentions. |
| Skills | `core/skills_manager.py`, `skills/<id>/` | Discovery, validation, progressive disclosure, safe install, legacy migration. |
| Attachments | `core/attachments.py`, `ui/attachment_tray.py` | Validation, storage, thumbnails, model derivatives, chat metadata. |
| Memory | `core/memory.py` | Atomic chat JSON persistence and titles. |
| Logging | `core/logger.py` | JSONL event log plus the `event_logged` Qt signal for Dev Mode. |
| Platform | `core/hardware_monitor.py`, `core/desktop_manager.py` | CPU/RAM/GPU snapshots and virtual-desktop switching. |
| UI | `ui/` | Windows, docks, composer, completion popup, toasts, theme, icons. |
| Packaging | `scripts/build.py`, `scripts/validate_skills.py`, `packaging/` | PyInstaller bundles, skill validation, installers. |

---

## 4. Class diagram

```mermaid
classDiagram
    class MainWindow {
        +str chat_id
        +AIEngine ai_engine
        +AIWorker worker
        +AttachmentTray tray
        +ChatInput input_field
        +send_message()
        +cancel_request()
        +open_settings()
        +closeEvent()
    }

    class AIWorker {
        +Event cancel_event
        +run()
        +cancel()
    }

    class TitleWorker {
        +run()
        +cancel()
    }

    class MCPConnectWorker {
        +run()
    }

    class AIEngine {
        +str chat_id
        +DevLogger logger
        +MCPManager mcp_manager
        +ToolRegistry registry
        +process_message()
        +connect_mcp()
        +refresh_settings()
        +switch_chat()
        +close()
    }

    class BaseProvider {
        <<abstract>>
        +int max_iterations
        +str tool_profile
        +str tool_choice
        +execute_tool()
        +run_text_tool_calls()
        +finalize()
        +finalize_exhausted()
        +run()
    }

    class OpenAICompatibleProvider {
        +run()
    }
    class GeminiProvider {
        +run()
    }
    class AnthropicProvider {
        +run()
    }

    class ToolRegistry {
        +register()
        +unregister()
        +names()
        +call_result()
        +as_openai_schema()
        +as_anthropic_schema()
        +as_gemini_declarations()
    }

    class ToolResult {
        +str name
        +bool ok
        +str content
        +str error
        +int duration_ms
        +failed
    }

    class DevLogger {
        +Signal event_logged
        +log()
        +tail()
    }

    class MCPManager {
        +connect_all()
        +close()
        +shutdown()
        +list_tools()
        +status()
        +find_tool()
        +call_tool()
    }

    class MCPTool {
        +str server_id
        +str name
        +dict input_schema
        +qualified_name
        +mention
    }

    class MCPServerStatus {
        +str server_id
        +bool connected
        +int tool_count
        +str error
        +summary()
    }

    class SkillInfo {
        +str id
        +str description
        +list allowed_tools
        +bool read_only
        +bool enabled
        +bool valid
        +has_code
    }

    class ChatInput {
        +Signal expandedChanged
        +Signal heightChanged
        +set_compact_width()
        +set_height_limits()
        +is_expanded()
    }

    class AttachmentTray {
        +add_paths()
        +add_image_bytes()
        +take()
        +clear_discard()
    }

    MainWindow *-- AIEngine : owns
    MainWindow *-- AttachmentTray : owns
    MainWindow *-- ChatInput : owns
    MainWindow ..> AIWorker : starts
    MainWindow ..> TitleWorker : starts
    MainWindow ..> MCPConnectWorker : starts
    MainWindow ..> DevLogger : connects signal
    AIEngine o-- ToolRegistry : builds
    AIEngine *-- MCPManager : owns
    AIEngine *-- DevLogger : owns
    AIEngine ..> BaseProvider : creates
    BaseProvider <|-- OpenAICompatibleProvider
    BaseProvider <|-- GeminiProvider
    BaseProvider <|-- AnthropicProvider
    BaseProvider --> ToolRegistry : filtered schemas
    ToolRegistry ..> ToolResult : returns
    MCPManager o-- MCPTool : discovers
    MCPManager o-- MCPServerStatus : reports
    AIEngine ..> SkillInfo : discovers
```

---

## 5. End-to-end message flow

```mermaid
sequenceDiagram
    autonumber
    actor U as User
    participant MW as MainWindow
    participant W as AIWorker QThread
    participant TW as TitleWorker QThread
    participant E as AIEngine
    participant L as DevLogger
    participant M as memory
    participant P as Provider
    participant R as ToolRegistry
    participant LLM as Model API
    participant T as Tools and OS

    U->>MW: type text + optional attachments, press Enter
    MW->>MW: _send_message(): slash command? tray.take()
    alt slash command without attachments
        MW->>MW: _process_slash_command()
    else normal turn
        MW->>MW: render user message, disable input, show spinner
        MW->>W: start AIWorker(engine, chat_id, text, attachments)
        W->>E: process_message(text, attachments, chat_id)
        E->>L: log("user_message")
        E->>M: load_chat(chat_id)
        M-->>E: user/assistant history
        E->>E: skills catalog + @skill bodies
        E->>E: MCP mention hints
        E->>E: build SYSTEM_INSTRUCTION_TEMPLATE
        E->>E: get_provider_instance()
        E->>E: build attachment manifest (pixels only if vision)
        E->>P: run(prompt, system_instruction, history, attachments)
        P->>R: filtered tool schema for profile
        P->>L: log("model_request")
        loop agent loop, max_agent_iterations
            P->>LLM: messages + tool schemas
            LLM-->>P: text or native tool calls
            P->>L: log("model_response", usage)
            opt tool calls
                P->>R: call_result(name, arguments)
                R->>T: execute tool
                T-->>R: text / Error:
                R-->>P: ToolResult
                P->>L: log("tool_result" or "tool_error" or "tool_effect")
                P->>LLM: tool result in provider wire format
            end
        end
        P-->>E: final answer text
        E->>M: save_chat(chat_id, prompt, answer, attachments)
        E->>L: log("delivered")
        E-->>W: response text
        W-->>MW: response_ready(chat_id, text)
        MW->>MW: render answer, reset input, refresh history
        opt first response in this chat
            MW->>TW: start TitleWorker(first_message)
            TW->>E: process_message(purpose="title", save_to_memory=False)
            TW-->>MW: title_generated(chat_id, title)
            MW->>M: set_chat_title(chat_id, title)
        end
    end
```

Cancellation is cooperative: `AIWorker.cancel()` sets a `threading.Event`;
providers call `_check_cancelled()` at each loop boundary and raise
`RequestCancelled`. The UI is restored in `_on_worker_finished`, never by
joining the thread from the click handler.

---

## 6. Agent loop and tool execution

```mermaid
sequenceDiagram
    autonumber
    participant P as Provider
    participant R as ToolRegistry
    participant L as DevLogger
    participant LLM as Model

    P->>R: names() + as_*_schema()
    R-->>P: tools allowed by tool_profile
    loop up to max_iterations
        P->>LLM: request
        LLM-->>P: assistant message
        alt native tool calls
            loop each call
                P->>P: parse JSON arguments
                alt invalid JSON or not an object
                    P->>L: log("tool_error")
                    P->>LLM: Error: invalid arguments
                else same name + same args as last call
                    P->>L: log("tool_error")
                    P->>LLM: Error: repeated call, answer instead
                else valid call
                    P->>R: call_result(name, args)
                    R->>R: validate required/types/enums, coerce integral floats
                    R-->>P: ToolResult(ok, content, error, duration_ms)
                    P->>L: log("tool_result" or "tool_error")
                    P->>L: log("tool_effect") when the tool has a visible effect
                    P->>LLM: result in native format
                end
            end
        else no tool calls
            P->>P: extract_tool_calls(text)
            alt JSON-text tool call
                P->>R: execute recovered calls
                P->>LLM: results as a user/tool message
            else ordinary answer
                P->>L: log("final_answer")
                P-->>P: return finalize()
            end
        end
    end
    P->>L: log("iteration_limit")
    P->>L: log("final_answer")
    P-->>P: return finalize_exhausted()
```

Tool results are truncated to `max_tool_result_chars` (default 20 000) with an
explicit `[... N characters omitted ...]` marker. A tool that returns `Error:`
or `BLOCKED:` counts as failed even when it did not raise, so Dev Mode and
Anthropic's `is_error` flag agree.

### Tool profiles

| Profile | Groups exposed | Typical use |
|---|---|---|
| `full` | filesystem, browser, system, mouse, skills, MCP | Capable models on a trusted machine. |
| `compact` (default) | filesystem, browser, system, skills, MCP | Small local models; keeps the schema list short. |
| `read-only` | `list_project_files`, `read_text_file`, `load_skill`, `read_skill_reference`, `browser_read_page`, `browser_list_interactive_elements`, `get_hardware_status`, plus `allowed-tools` of enabled read-only skills | Inspection without side effects. MCP tools are excluded. |

`tool_choice` maps to `auto` / `required` / `none` on OpenAI-compatible
backends and to `auto` / `any` / `none` on Anthropic. `parallel_tool_calls` is
accepted by the provider constructors; Gemini and Anthropic collect every call
of a turn before sending the result block.

---

## 7. MCP lifecycle

```mermaid
sequenceDiagram
    autonumber
    participant MW as MainWindow
    participant CW as MCPConnectWorker
    participant E as AIEngine
    participant MM as MCPManager
    participant LT as asyncio loop thread
    participant S as MCP server
    participant R as ToolRegistry
    participant L as DevLogger

    Note over MW: QTimer.singleShot(0, _start_mcp_connect)
    MW->>CW: start
    CW->>E: connect_mcp()
    E->>MM: connect_all()
    MM->>MM: close() previous sessions
    loop each enabled server in settings.mcp_servers
        MM->>LT: _run(_connect_server(server))
        LT->>S: open stdio subprocess or HTTP client
        S-->>LT: session
        LT->>S: list_tools()
        S-->>LT: tool definitions
        LT-->>MM: AsyncExitStack + client + tools
        MM->>MM: keep session alive, record MCPServerStatus
    end
    MM-->>E: statuses
    E->>R: _build_registry(): core + skills + MCP tools
    E->>L: log("mcp_connect", statuses)
    E-->>CW: statuses
    CW-->>MW: done(statuses)
    MW->>MW: refresh MCP tool completion, warn on first failure
```

Each server keeps one `AsyncExitStack` open for the whole app session; closing a
stdio session kills its subprocess, so `close()` is only used when reconnecting
or shutting down. `MCPManager.call_tool` runs the coroutine on the loop thread
with `mcp_call_timeout` (default 60 s), flattens the result to text, and turns
timeouts and exceptions into `Error: ...` strings the model can read.

```mermaid
flowchart LR
    MODEL["Model calls<br/>mcp__server__tool"] --> REG["ToolRegistry"]
    REG --> BRIDGE["mcp.registry call_mcp()"]
    BRIDGE --> MGR["MCPManager.call_tool()"]
    MGR --> FIND["find_tool()"]
    MGR --> LOOP["asyncio.run_coroutine_threadsafe"]
    LOOP --> SESSION["Live client session"]
    SESSION --> SERVER["MCP server"]
    SERVER --> TEXT["_format_content()<br/>text · images omitted · structured JSON"]
    TEXT --> MODEL
```

User mentions are parsed by `core/mcp/mentions.py`. `;server.tool` (optionally
followed by a JSON object) adds a hint to the system prompt; it does not execute
the tool directly. The model still makes the actual call through the registry.

---

## 8. Skills: discovery, activation, installation

```mermaid
flowchart TD
    START([Startup or Settings/Skills save]) --> SCAN["discover_skills()"]
    SCAN --> LOOP{"skills/ entry"}
    LOOP -->|SKILL.md| FM["read YAML frontmatter only"]
    LOOP -->|legacy skill.json| LEGACY["SkillInfo(legacy=True, warning)"]
    LOOP -->|other| SKIP["ignore"]
    FM --> VALIDATE["validate_skill()<br/>required fields · body size · refs · paths · scripts · symlinks"]
    VALIDATE --> INFO["SkillInfo(issues, enabled, has_code)"]
    LEGACY --> INFO
    INFO --> ENABLED{"id in enabled_skills?"}
    ENABLED -->|no| CATALOG["catalog only, never imported"]
    ENABLED -->|yes + valid| REGISTER["register_skill_tools()<br/>load_skill · read_skill_reference"]
    REGISTER --> CODE{"skill.py?"}
    CODE -->|yes| IMPORT["import skill.py and call register(registry)"]
    CODE -->|no| DONE([Ready])
    IMPORT --> DONE
```

```mermaid
sequenceDiagram
    autonumber
    actor U as User
    participant E as AIEngine
    participant S as skills_manager
    participant P as Provider
    participant R as ToolRegistry

    E->>S: catalog_text()
    S-->>E: compact catalog of enabled skills (id, description, tags)
    alt user wrote @skill-id
        E->>S: mentioned_skill_ids(prompt)
        E->>S: activated_skills_text(ids)
        S-->>E: full body of those skills, this turn only
        E->>E: log("skills_activated")
    end
    E->>P: run(prompt, system_instruction)
    opt model needs a skill body later
        P->>R: load_skill(name)
        R->>S: load_skill_body(name)
        S-->>R: instructions
        R-->>P: text result
    end
```

Skill bodies are never embedded in the chat history: the catalog is rebuilt
from settings on every turn, and `@skill` activation lasts one request.
`skill.py` is imported only for enabled, valid skills that ship code; import
failures print `[SkillsManager] ...` and are skipped.

Installation is a separate, confirmation-gated path:

```mermaid
flowchart LR
    SRC["Folder or .zip"] --> CHECK["_check_tree()<br/>≤ 200 files · ≤ 10 MB · ≤ 2 MB/file · no symlinks"]
    CHECK --> ZIP{"zip?"}
    ZIP -->|yes| SAFE["_safe_extract()<br/>no zip-slip · no absolute paths · no backslashes"]
    ZIP -->|no| INSPECT
    SAFE --> INSPECT["inspect_skill_folder()<br/>metadata + tree SHA-256 + issues"]
    INSPECT --> CONFIRM{"confirm(summary)?"}
    CONFIRM -->|no| CANCEL["Installation cancelled"]
    CONFIRM -->|yes| COPY["copytree into skills/SKILL_ID<br/>write .install.json with SHA-256"]
    COPY --> ENABLE["User enables it in Skills dialog"]
```

---

## 9. Attachments pipeline

```mermaid
flowchart TD
    INPUT["Paste (Ctrl+V) · drag & drop · clip button"] --> BYTES["bytes or local path"]
    BYTES --> EMPTY{"empty?"}
    EMPTY -->|yes| REJECT["AttachmentError → toast"]
    EMPTY -->|no| SVG{"looks like SVG?"}
    SVG -->|yes| REJECT
    SVG -->|no| MAGIC["magic-byte detection<br/>PNG · JPEG · GIF · WebP"]
    MAGIC --> LIMITS{"size and pixels within limits?"}
    LIMITS -->|no| REJECT
    LIMITS -->|yes| STORE["copy to workspace/uploads/chat_id/uuid_name"]
    STORE --> KIND{"image?"}
    KIND -->|no| META["metadata: id · kind · name · path · mime · size · sha256 · index"]
    KIND -->|yes| DERIVE["Pillow: verify · EXIF transpose · thumbnail shown at 72 px<br/>model copy ≤ 1568 px, JPEG q85 or PNG with alpha"]
    DERIVE --> META
    META --> TRAY["AttachmentTray chip #n"]
    TRAY --> SEND["_send_message() → tray.take()"]
    SEND --> MANIFEST["build_manifest(): numbered text always"]
    MANIFEST --> VISION{"active model supports vision?"}
    VISION -->|yes| PIXELS["current turn's model images attached"]
    VISION -->|no| SKIP["manifest only + attachments_skipped toast"]
    PIXELS --> PROVIDER["Provider multimodal payload"]
    SKIP --> PROVIDER
    PROVIDER --> SAVE["save_chat(): public_metadata only"]
```

Limits: 10 attachments, 20 MB per image, 50 MB per other file, 50 MP, no SVG,
no animated GIF/WebP. Reordering renumbers `index` 1..n; older turns keep their
manifest text but their pixels are not re-sent.

---

## 10. Chat persistence and switching

```mermaid
sequenceDiagram
    autonumber
    participant MW as MainWindow
    participant M as memory
    participant FS as Chat JSON file
    participant TW as TitleWorker

    MW->>M: load_chat(chat_id)
    M->>FS: read JSON
    FS-->>M: messages
    M-->>MW: list[dict]

    MW->>M: save_chat(chat_id, prompt, answer, attachments)
    M->>M: sanitize_chat_id()
    M->>FS: read the chat JSON (to preserve title)
    M->>M: append user + assistant messages
    M->>FS: write .tmp then Path.replace() atomically
    Note over M,FS: one re-entrant lock serializes writers

    MW->>TW: start after first response
    TW->>M: set_chat_title(chat_id, title)
    M->>FS: rewrite JSON with title
    MW->>M: list_chats()
    M-->>MW: id · title · message_count · last_updated
```

Chat ids are sanitized to a safe filename; titles live inside the JSON (not in
the filename) and survive `save_chat`. `AIEngine.switch_chat()` changes only the
chat id, keeping the registry and the Dev Logger connection alive. A turn binds
its chat id once, so switching windows mid-request cannot redirect the answer.

---

## 11. UI threading model

```mermaid
flowchart TB
    subgraph GUI["GUI thread"]
        MW["MainWindow"]
        CONSOLE["DevConsole"]
        TOASTS["ToastManager"]
        TIMERS["QTimer / animations"]
    end

    subgraph Workers["Worker threads"]
        AIW["AIWorker"]
        TW["TitleWorker"]
        MCPW["MCPConnectWorker"]
    end

    subgraph MCPThread["MCP daemon thread"]
        LOOP["asyncio event loop"]
        SESS["MCP client sessions"]
    end

    MW -->|start| AIW
    MW -->|start| TW
    MW -->|start| MCPW
    AIW -->|response_ready / error_occurred queued| MW
    TW -->|title_generated queued| MW
    MCPW -->|done queued| MW
    AIW -->|DevLogger.log| BUS["event_logged signal"]
    MCPW -->|DevLogger.log| BUS
    BUS -->|queued| CONSOLE
    BUS -->|queued| MW
    MW -->|tool_effect toast| TOASTS
    MCPW -->|connect_all / call_tool| LOOP
    LOOP --> SESS
```

Rules:

- Never destroy a running `QThread`: `closeEvent` cancels and waits for every
  worker, and title workers are kept in a set until `finished`.
- `DevLogger.log()` is safe from any thread; Qt queues `event_logged` to the GUI
  thread.
- The MCP manager refuses calls made from its own loop thread, preventing
  deadlocks.
- Long operations (model call, MCP startup) never run on the GUI thread.

### Composer state machine

```mermaid
stateDiagram-v2
    [*] --> Compact
    Compact --> Expanded: text has a newline or is wider than the compact field
    Expanded --> Compact: text fits again after editing
    Compact: attach + field + send on one row, 52 px minimum, grows with wrapped lines
    Expanded: full-width floating field with buttons below, 90 px to 50 percent of the window
    note right of Expanded
        Comparison uses the stored compact width,
        so widening the panel does not flip back.
    end note
```

The composer floats over the conversation: `MainWindow` reserves bottom
viewport margins instead of shrinking the chat. `ChatInput.heightChanged`
drives the clearance, and `expandedChanged` swaps the grid layout.

---

## 12. Deployment and data locations

```mermaid
flowchart LR
    subgraph Dev["Source checkout"]
        CODE["config.py + core/ + ui/"]
        BASE1["BASE_DIR = repository root"]
    end

    subgraph Frozen["PyInstaller bundle"]
        EXE["AI Desktop Assistant"]
        BASE2["Per-user data dir<br/>%APPDATA% · ~/Library/Application Support · $XDG_DATA_HOME"]
    end

    subgraph Portable["AI_ASSISTANT_HOME set"]
        BASE3["Custom directory"]
    end

    CODE --> BASE1
    EXE --> BASE2
    CODE -.->|override| BASE3
    BASE1 --> DIRS["settings.json · data/chats · logs · workspace/uploads · skills"]
    BASE2 --> DIRS
    BASE3 --> DIRS
```

`config.py` creates `logs/`, `workspace/uploads/` and `skills/` on import;
`core.memory` creates `data/chats/`. On a relocated install, bundled example
skills are copied into the writable `skills/` directory once.

Release artifacts are built by `scripts/build.py` (PyInstaller onedir, archive,
`SHA256SUMS`) and `.github/workflows/release.yml` (wheel/sdist, CycloneDX SBOM,
Windows installer, macOS DMG, GitHub release, PyPI trusted publishing).
Chromium is not bundled; run `playwright install chromium` after installing.

---

## 13. Invariants worth preserving

1. **One registry.** Core tools, skill tools and MCP tools all register in
   `core.tools.REGISTRY`; providers never keep their own tool tables.
2. **Engine stays transport-free.** No OpenAI/Gemini/Anthropic types in
   `core/ai_engine.py`.
3. **Provider loops log consistently.** Use `BaseProvider.execute_tool()` and
   `report_tool_error()`, not `REGISTRY.call()` directly.
4. **Atomic memory writes.** `save_chat` goes through `.tmp` + `Path.replace()`
   under the module lock.
5. **Attachment pixels are derived.** Chats keep metadata; `load_model_image()`
   reads the downscaled copy from disk.
6. **MCP tools are ephemeral.** `_build_registry()` unregisters every `mcp__*`
   tool before re-registering the currently connected servers.
7. **Skills are opt-in.** Discovery never imports code; only `enabled_skills`
   with a valid manifest and `skill.py` are executed.
8. **GUI thread stays responsive.** Any blocking call belongs in a worker.

## Where to change what

| Change | Files |
|---|---|
| Add a core tool | Implement and register in `core/tools/<module>.py`; add its group in `config.TOOL_GROUPS`; `_build_registry()` already registers the module. |
| Add a provider type | One `ProviderSpec` in `core/providers/__init__.py` plus a `BaseProvider` subclass. |
| Change the system prompt | `SYSTEM_INSTRUCTION_TEMPLATE` in `core/ai_engine.py`. |
| Add a slash command | `ui/commands.py` and `MainWindow._process_slash_command()`. |
| Change theme tokens | `ui/theme.py` (tokens + the single global stylesheet). |
| Change attachment limits | `core/attachments.py`. |
| Change MCP timeouts | `config.DEFAULT_SETTINGS["mcp_call_timeout"]` and `core/mcp/manager.py` defaults. |
