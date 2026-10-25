"""Tool-call recovery for models that answer with JSON text."""

from core.providers.tool_text import extract_tool_calls
from core.tools import ToolRegistry


def make_registry():
    registry = ToolRegistry()
    registry.register(
        "echo",
        "Echo text back.",
        {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        lambda text: f"echo:{text}",
    )
    return registry


def test_plain_object():
    calls = extract_tool_calls('{"tool": "echo", "arguments": {"text": "hi"}}', make_registry())
    assert calls == [("echo", {"text": "hi"})]


def test_fenced_object_wrapped_in_prose_is_not_executed():
    content = 'Sure, I will call the tool:\n```json\n{"tool": "echo", "arguments": {"text": "hi"}}\n```\n'
    calls = extract_tool_calls(content, make_registry())
    assert calls == []


def test_tool_calls_batch():
    content = '{"tool_calls": [{"name": "echo", "arguments": {"text": "a"}}, {"name": "echo", "arguments": {"text": "b"}}]}'
    calls = extract_tool_calls(content, make_registry())
    assert calls == [("echo", {"text": "a"}), ("echo", {"text": "b"})]


def test_openai_style_function_object():
    content = '{"function": {"name": "echo", "arguments": "{\\"text\\": \\"hi\\"}"}}'
    calls = extract_tool_calls(content, make_registry())
    assert calls == [("echo", {"text": "hi"})]


def test_shorthand_single_key_object():
    calls = extract_tool_calls('{"echo": {"text": "hi"}}', make_registry())
    assert calls == [("echo", {"text": "hi"})]


def test_fenced_array():
    content = '```json\n[{"tool": "echo", "arguments": {"text": "hi"}}]\n```'
    calls = extract_tool_calls(content, make_registry())
    assert calls == [("echo", {"text": "hi"})]


def test_unknown_tool_is_not_executed():
    assert extract_tool_calls('{"tool": "rm_rf", "arguments": {}}', make_registry()) == []


def test_bare_name_without_arguments_is_not_executed():
    assert extract_tool_calls('{"name": "echo"}', make_registry()) == []
    assert extract_tool_calls('[{"name": "echo"}]', make_registry()) == []


def test_parameters_key_is_accepted_only_for_tool_calls():
    assert extract_tool_calls(
        '{"tool": "echo", "parameters": {"text": "hi"}}', make_registry()
    ) == [("echo", {"text": "hi"})]
    assert extract_tool_calls(
        '{"name": "echo", "parameters": {"text": "hi"}}', make_registry()
    ) == []


def test_explicit_empty_arguments_are_allowed():
    assert extract_tool_calls('{"tool": "echo", "arguments": {}}', make_registry()) == [("echo", {})]


def test_null_arguments_are_not_executed():
    assert extract_tool_calls('{"tool": "echo", "arguments": null}', make_registry()) == []


def test_non_string_content_is_ignored():
    assert extract_tool_calls([{"tool": "echo", "arguments": {"text": "hi"}}], make_registry()) == []


def test_plain_json_answer_is_not_executed():
    assert extract_tool_calls('{"answer": 42}', make_registry()) == []


def test_malformed_json_is_ignored():
    assert extract_tool_calls('{"tool": "echo", ', make_registry()) == []
