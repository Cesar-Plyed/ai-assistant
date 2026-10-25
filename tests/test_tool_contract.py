"""Contract tests between the system prompt and the real tool registry."""

import re

from core.ai_engine import SYSTEM_INSTRUCTION_TEMPLATE, _build_registry
from core.tools import REGISTRY

# Identifiers that look like tool names (snake_case, at least one underscore).
_TOOL_TOKEN_RE = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b")


def test_prompt_only_mentions_registered_tools():
    registry = _build_registry()
    mentioned = set(_TOOL_TOKEN_RE.findall(SYSTEM_INSTRUCTION_TEMPLATE))
    missing = sorted(name for name in mentioned if name not in registry.names())
    assert not missing, f"System prompt mentions unregistered tools: {missing}"


def test_no_phantom_tools():
    _build_registry()
    assert not REGISTRY.has("open_browser")
    assert not REGISTRY.has("fetch_web_page_text")


def test_core_browser_tools_registered():
    registry = _build_registry()
    expected = [
        "browser_goto",
        "browser_read_page",
        "browser_list_interactive_elements",
        "browser_click",
        "browser_fill",
        "browser_set_checkbox",
        "browser_select_option",
        "browser_press_key",
        "browser_scroll",
        "browser_type_text",
    ]
    missing = [name for name in expected if not registry.has(name)]
    assert not missing, f"Missing browser tools: {missing}"
