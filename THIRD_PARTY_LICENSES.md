# Third-Party Licenses

This project bundles or depends on the following third-party software. Each
dependency retains its own license; this file is an informational summary, not
a substitute for the full license text.

## PySide6 — LGPLv3

The Qt for Python bindings (`PySide6`) are licensed under the GNU Lesser
General Public License version 3 (LGPLv3). The project itself is licensed
under the MIT license. LGPLv3 is compatible with MIT: you may use, modify,
and distribute this software provided you comply with both licenses.

- Project home: https://www.qt.io
- License: https://www.gnu.org/licenses/lgpl-3.0.html

## Other Dependencies

| Package | License | Purpose |
|---------|---------|---------|
| openai | MIT | OpenAI-compatible LLM client |
| google-genai | Apache 2.0 | Google Gemini client |
| anthropic | MIT | Anthropic Claude client |
| psutil | BSD 3-Clause | System / hardware monitoring |
| playwright | BSD 3-Clause | Browser automation |
| pyautogui | BSD 2-Clause | Mouse/keyboard control |
| markdown | BSD 3-Clause | Markdown rendering |
| beautifulsoup4 | MIT | HTML parsing |
| requests | Apache 2.0 | HTTP client |
| Pillow | PIL License | Image processing |
| PyYAML | MIT | YAML parsing |
| mcp | MIT | Model Context Protocol |
| pytest | MIT | Testing |
| pytest-qt | MIT | Qt testing |
| pytest-cov | BSD | Coverage |
| ruff | MIT | Linting |
| pyinstaller | GPLv2+with-exception | Packaging |

See `pyproject.toml` and `uv.lock` for exact versions.