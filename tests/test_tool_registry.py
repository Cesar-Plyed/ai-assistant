"""Contract tests for the tool registry used by every provider."""

import pytest

import config
from core.tools import ToolRegistry


@pytest.fixture
def calls():
    return []


@pytest.fixture
def registry(calls):
    registry = ToolRegistry()

    def echo(text):
        calls.append(("echo", text))
        return f"echo:{text}"

    registry.register(
        "echo",
        "Echo text back.",
        {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        echo,
    )

    def add(a, b):
        calls.append(("add", a, b))
        return str(a + b)

    registry.register(
        "add",
        "Add two integers.",
        {
            "type": "object",
            "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
            "required": ["a", "b"],
        },
        add,
    )

    def pick(mode):
        calls.append(("pick", mode))
        return mode

    registry.register(
        "pick",
        "Pick one mode.",
        {
            "type": "object",
            "properties": {"mode": {"type": "string", "enum": ["fast", "slow"]}},
            "required": ["mode"],
        },
        pick,
    )

    def boom():
        calls.append(("boom",))
        raise RuntimeError("kaboom")

    registry.register("boom", "Always fails.", {"type": "object", "properties": {}}, boom)

    return registry


def test_successful_call_returns_structured_result(registry, calls):
    result = registry.call_result("echo", {"text": "hi"})

    assert result.ok is True
    assert result.failed is False
    assert result.content == "echo:hi"
    assert result.duration_ms >= 0
    assert calls == [("echo", "hi")]


def test_unknown_tool_fails_without_raising(registry, calls):
    result = registry.call_result("missing", {})

    assert result.ok is False
    assert result.failed is True
    assert result.content.startswith("Error:")
    assert "missing" in result.content
    assert calls == []


def test_missing_required_argument_does_not_call_tool(registry, calls):
    result = registry.call_result("echo", {})

    assert result.ok is False
    assert result.failed is True
    assert "text" in result.content
    assert calls == []


def test_wrong_argument_type_does_not_call_tool(registry, calls):
    result = registry.call_result("add", {"a": "x", "b": 1})

    assert result.ok is False
    assert result.failed is True
    assert "a" in result.content
    assert "integer" in result.content
    assert calls == []


def test_optional_null_is_accepted(registry, calls):
    def move(x=None):
        calls.append(("move", x))
        return "moved"

    registry.register(
        "move",
        "Move somewhere.",
        {"type": "object", "properties": {"x": {"type": "integer"}}},
        move,
    )

    result = registry.call_result("move", {"x": None})

    assert result.ok is True
    assert calls == [("move", None)]


def test_integral_float_is_accepted_for_integer(registry, calls):
    result = registry.call_result("add", {"a": 1.0, "b": 2.0})

    assert result.ok is True
    assert result.content == "3"
    assert calls == [("add", 1, 2)]


def test_fractional_float_is_rejected_for_integer(registry, calls):
    result = registry.call_result("add", {"a": 1.5, "b": 2})

    assert result.ok is False
    assert "integer" in result.content
    assert calls == []


def test_nested_integer_floats_are_coerced(registry, calls):
    def nested(payload, items):
        calls.append(("nested", payload, items))
        return "ok"

    registry.register(
        "nested",
        "Nested integer properties.",
        {
            "type": "object",
            "properties": {
                "payload": {
                    "type": "object",
                    "properties": {"n": {"type": "integer"}},
                },
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"n": {"type": "integer"}},
                    },
                },
            },
        },
        nested,
    )

    result = registry.call_result(
        "nested", {"payload": {"n": 1.0}, "items": [{"n": 2.0}]}
    )

    assert result.ok is True
    assert calls == [("nested", {"n": 1}, [{"n": 2}])]


def test_union_integer_float_is_coerced(registry, calls):
    def maybe(n):
        calls.append(("maybe", n))
        return "ok"

    registry.register(
        "maybe",
        "Optional integer.",
        {"type": "object", "properties": {"n": {"type": ["integer", "null"]}}},
        maybe,
    )

    result = registry.call_result("maybe", {"n": 3.0})

    assert result.ok is True
    assert calls == [("maybe", 3)]
    assert isinstance(calls[0][1], int)


def test_invalid_enum_does_not_call_tool(registry, calls):
    result = registry.call_result("pick", {"mode": "turbo"})

    assert result.ok is False
    assert result.failed is True
    assert "fast" in result.content and "slow" in result.content
    assert calls == []


def test_tool_exception_is_reported_with_its_type(registry, calls):
    result = registry.call_result("boom", {})

    assert result.ok is False
    assert result.failed is True
    assert "RuntimeError" in result.content
    assert calls == [("boom",)]


def test_blocked_tool_result_is_treated_as_failure(registry, calls):
    def blocked():
        calls.append(("blocked",))
        return "BLOCKED: ask the user first."

    registry.register("blocked", "Needs confirmation.", {"type": "object", "properties": {}}, blocked)

    result = registry.call_result("blocked", {})

    assert result.ok is True  # the tool ran; the action itself was gated
    assert result.failed is True
    assert result.content.startswith("BLOCKED:")


def test_long_result_is_truncated(registry, calls, monkeypatch):
    monkeypatch.setitem(config.SETTINGS, "max_tool_result_chars", 10)

    def long_text():
        calls.append(("long_text",))
        return "x" * 100

    registry.register("long_text", "Return a lot of text.", {"type": "object", "properties": {}}, long_text)

    result = registry.call_result("long_text", {})

    assert result.ok is True
    assert "truncated" in result.content
    assert len(result.content) < 100
    assert result.content.startswith("x" * 10)


def test_call_still_returns_a_plain_string(registry):
    assert registry.call("echo", {"text": "hi"}) == "echo:hi"


def test_schemas_keep_their_provider_formats(registry):
    anthropic_schema = registry.as_anthropic_schema()
    openai_schema = registry.as_openai_schema()

    assert anthropic_schema
    assert all("input_schema" in tool and "name" in tool for tool in anthropic_schema)
    assert openai_schema
    assert all(tool["type"] == "function" for tool in openai_schema)
    assert all("name" in tool["function"] and "parameters" in tool["function"] for tool in openai_schema)

    echo_anthropic = next(tool for tool in anthropic_schema if tool["name"] == "echo")
    echo_openai = next(tool for tool in openai_schema if tool["function"]["name"] == "echo")
    assert echo_anthropic["input_schema"] == echo_openai["function"]["parameters"]
