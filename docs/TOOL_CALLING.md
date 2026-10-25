# Tool calling

Every provider runs the same conceptual agent loop: send the conversation and
the allowed tool schemas, execute any tool calls, feed the results back, and
repeat until the model answers in natural language or the iteration budget runs
out. The loop lives in each provider's `run()`; shared helpers live in
`core/providers/base_provider.py`.

## Conversation shape

- The system instruction is sent as a real `system` message (or Gemini's
  `system_instruction`), never as `repr()` text.
- Chat history is replayed as real `user` / `assistant` turns.
- The current user turn carries the numbered attachment manifest and, for
  vision models, the image parts.
- Assistant tool-call turns and tool-result turns are appended in the
  provider's native format.

## Protocol in the system prompt

`SYSTEM_INSTRUCTION_TEMPLATE` tells the model to:

- use the native tool-calling channel and never write tool calls as JSON text;
- read a tool error, fix the arguments and retry at most once;
- ask before any Apply / Submit / Enviar / Postular action;
- always finish with natural language for the user.

## Native calls

1. The model returns one or more tool calls.
2. The provider parses the arguments and calls
   `BaseProvider.execute_tool(name, arguments)`.
3. `ToolRegistry.call_result()` checks the name, validates required fields,
   primitive types and enums, coerces integral floats to integers for
   `integer` properties, and runs the tool.
4. The result goes back as a tool message/block. Anthropic also receives
   `is_error=true` when the tool failed.
5. The loop continues with the next model request.

A tool is never run with empty or garbage arguments. Malformed native JSON is
reported to the model as an `Error:` result so it can retry.

## JSON-text rescue

Small local models sometimes ignore the `tools` parameter and answer with:

```json
{"tool": "list_project_files", "arguments": {"relative_path": "."}}
```

`core/providers/tool_text.py::extract_tool_calls()` recognises only shapes that
name a **registered** tool and carry an explicit argument object (or the
shorthand `{"tool_name": {...}}`). Ordinary JSON answers, tool inventories and
function definitions stay inert. When a call is recovered, it is executed and
the result is appended as a user/tool message; the loop continues.

## Guards

| Guard | Behaviour |
|---|---|
| Invalid arguments | `Error: invalid arguments for tool '…': …` is returned to the model; the tool does not run. |
| Unknown tool | `Error: tool '…' is not registered.` |
| Repeat call | The same tool with the same arguments as the immediately previous call is rejected with a "stop repeating and answer" error. |
| Result size | Results longer than `max_tool_result_chars` (default 20 000) are truncated with an explicit `[... N characters omitted ...]` marker. |
| Iteration limit | After `max_agent_iterations` (default 8), the provider logs `iteration_limit` and returns a summary of the executed tools, never raw tool-call JSON. |
| Cancellation | `_check_cancelled()` runs at every loop boundary and raises `RequestCancelled`. |

## Settings

| Setting | Default | Values / effect |
|---|---|---|
| `tool_profile` | `compact` | `full` · `compact` · `read-only`. Controls which core tools are advertised. |
| `tool_choice` | `auto` | `auto` · `required` · `off`. Mapped to `auto` / `required` / `none` (OpenAI-compatible) and `auto` / `any` / `none` (Anthropic). |
| `parallel_tool_calls` | `true` | Persisted and passed to provider constructors; the current loops execute every call returned in an assistant turn. |
| `max_agent_iterations` | `8` | Maximum model calls per user turn. |
| `max_tool_result_chars` | `20 000` | Truncation limit for one tool result. |
| `temperature` | `0.2` | Sampling temperature. |
| `max_tokens` | `4096` | Output limit (Anthropic defaults to 4096 when unset). |

### Profiles

| Profile | Tools |
|---|---|
| `full` | Filesystem, browser, system, mouse, skills and MCP. |
| `compact` (default) | Filesystem, browser, system, skills and MCP — the small-model default. |
| `read-only` | `list_project_files`, `read_text_file`, `load_skill`, `read_skill_reference`, `browser_read_page`, `browser_list_interactive_elements`, `get_hardware_status`, plus `allowed-tools` of enabled read-only skills. MCP tools are excluded. |

Tools registered by skills or MCP that do not belong to a known core group are
treated as custom and included in `full`/`compact`. Unknown profile names fall
back to `full`.

## Provider differences

| Provider | Tool format | Result format |
|---|---|---|
| OpenAI-compatible | `tools` + `tool_calls` | `role: "tool"` messages with `tool_call_id`. |
| Anthropic | `tools` + `tool_use` blocks | `user` turn with `tool_result` blocks and `is_error`. |
| Gemini | `FunctionDeclaration` list | One user turn containing a `function_response` part per call. |

## Dev Mode

`DevLogger` records `model_request`, `model_response` (finish reason and token
usage), `tool_call`, `tool_result` / `tool_error`, `tool_effect`, `final_answer`,
`iteration_limit`, `reasoning_content`, `mcp_connect`, `skills_activated`,
`attachments_skipped` and `delivered`. The Dev Console shows `request_id`,
`purpose` (`chat` / `title`), tool arguments and durations, and marks the final
delivery to the chat.

Successful side-effecting tools emit `tool_effect` from
`core/tools/effects.py`; `MainWindow` turns that event into a success toast.
