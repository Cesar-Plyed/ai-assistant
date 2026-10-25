# Security

This app gives a language model real access to your machine: it can read and
write files, run console commands, drive a browser and — when explicitly
enabled — control the mouse and keyboard. Treat the model's output as
untrusted input and the tool layer as the security boundary.

**The app is not a sandbox.** The filesystem tools accept absolute paths, the
console tool runs real commands, and the automation browser may be logged into
your accounts. Run it only with models and prompts you trust.

## Defaults and gates

| Control | Default | What it protects |
|---|---|---|
| `tool_profile` | `compact` | Keeps mouse tools and the largest schemas out of the default tool list. |
| `enable_mouse_control` | `false` | Mouse/keyboard tools return `BLOCKED` until enabled; the setting is re-read on every call. |
| `enable_browser_automation` | `true` | Master switch for every browser tool except `browser_close`. |
| `enable_browser_page_reading` | `true` | Gates `browser_read_page` and `browser_list_interactive_elements`. |
| `require_submit_confirmation` | `true` | Blocks clicks on Apply / Submit / Enviar / Postular-looking elements until the model retries with `confirmed=true`. |
| `read-only` profile | opt-in | Exposes only read tools plus `allowed-tools` of enabled read-only skills. MCP tools are excluded. |
| `dev_mode` | `false` | Shows the live event log; useful for auditing tool calls. |

The system prompt tells the model to ask before submitting a form and to respect
disabled tools. That is guidance, not enforcement — the enforcement is in
`core/tools/` (`BLOCKED:` results) and in the tool-profile filter.

## Tool risk

| Tool group | Risk | Mitigation |
|---|---|---|
| `run_console_command` | Arbitrary shell execution. | Only present in `compact`/`full`; logged in Dev Mode; 30 s timeout and truncated output. |
| `write_text_file` | Creates or overwrites any path the process can write. | Only present in `compact`/`full`; use `read-only` or `compact` with care. |
| `read_text_file` / `list_project_files` | Reads any readable path. | Included in `read-only`; do not point the app at secrets. |
| Browser tools | Acts inside the user's logged-in automation browser. | `enable_browser_automation`, page-reading gate, submit confirmation. |
| Mouse/keyboard tools | Full desktop control. | Off by default; `full` profile only; re-checked per call. |

## Skills

- Discovery reads `SKILL.md` frontmatter only and **never imports code**.
- `skill.py` is imported only for skills the user enabled, that are valid, and
  that actually ship code. Import errors are printed and skipped.
- Installation requires an explicit confirmation callback. Before copying, the
  installer checks size (≤ 10 MB, ≤ 2 MB per file, ≤ 200 files), rejects
  symlinks, absolute paths, drive letters, backslashes and zip-slip, and records
  a tree SHA-256 in `.install.json`.
- Validation rejects absolute paths and undeclared scripts, and warns about
  unknown `allowed-tools`.
- A read-only skill's declared `allowed-tools` are added to the `read-only`
  profile; without that declaration its `skill.py` tools stay out.

## MCP

- Only servers with `enabled: true` are connected.
- Disabled servers never start; a failed server is isolated and reported in its
  status.
- MCP tools are excluded from the `read-only` profile.
- `stdio` servers inherit the process environment plus their own `env`; HTTP
  headers come from the server entry. Keep tokens out of committed files.
- MCP tool results are flattened to text; image content is replaced with
  `[image content omitted]`.
- Calls are bounded by `mcp_call_timeout` (default 60 s) and the manager refuses
  calls from its own event-loop thread.

## Attachments

- Files are validated by magic bytes, not extension.
- Limits: 10 per message, 20 MB/image, 50 MB/file, 50 MP; SVG and animated
  images are refused.
- Originals are copied to `workspace/uploads/`; chat JSON stores metadata and
  paths, never base64.
- The model receives a downscaled, metadata-stripped derivative; only the
  current turn's pixels are sent.

## Secrets and logs

- Prefer environment variables: `<PROVIDER_ID>_API_KEY`, the preset `env_var`,
  or `ANTHROPIC_API_KEY` / `GEMINI_API_KEY`. Environment variables override
  `settings.json`.
- Never commit `settings.json`, `data/`, `logs/` or `workspace/`. `.gitignore`
  already excludes them.
- Dev Mode logs contain prompts, tool arguments and tool output, which may
  include sensitive data. Treat `logs/*.jsonl` as private.
- API keys are not written to the Dev log, but a tool result could echo one if
  you ask it to read a file containing it.

## Reporting

Report vulnerabilities privately to the maintainer (see `LICENSE` for contact)
rather than opening a public issue. Include the version, the affected tool or
provider, and a minimal reproduction with secrets redacted.
