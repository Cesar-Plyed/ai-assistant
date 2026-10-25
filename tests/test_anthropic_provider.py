"""Agent-loop behavior of the native Anthropic provider, with a fake client."""

import inspect
from types import SimpleNamespace

import anthropic
import pytest

from core.providers.anthropic_provider import AnthropicProvider
from core.tools import ToolRegistry
from tests.fakes import FakeLogger


# Bind fake request kwargs to the real SDK signature. This catches parameters
# that the installed SDK no longer accepts (e.g. `temperature` in anthropic 2.x)
# even though the fake client would happily swallow them.
_REAL_CREATE_SIGNATURE = inspect.signature(anthropic.Anthropic(api_key="test").messages.create)


class FakeBlock(SimpleNamespace):
    def model_dump(self, exclude_none=True):
        data = dict(self.__dict__)
        if exclude_none:
            data = {key: value for key, value in data.items() if value is not None}
        return data


def text_block(text):
    return FakeBlock(type="text", text=text)


def tool_use_block(tool_id="toolu_1", name="echo", tool_input=None):
    return FakeBlock(type="tool_use", id=tool_id, name=name, input=tool_input or {})


class FakeResponse:
    def __init__(self, content, stop_reason=None):
        self.content = content
        self.stop_reason = stop_reason


class FakeMessages:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        _REAL_CREATE_SIGNATURE.bind(**kwargs)
        self.calls.append(kwargs)
        return self._responses.pop(0)


class FakeClient:
    def __init__(self, responses):
        self.messages = FakeMessages(responses)


@pytest.fixture
def make_provider(monkeypatch):
    def _make(responses, config=None, max_iterations=8):
        client = FakeClient(responses)
        monkeypatch.setattr(anthropic, "Anthropic", lambda **kwargs: client)

        registry = ToolRegistry()
        executed = []

        def echo(text):
            executed.append(text)
            return f"echo:{text}"

        registry.register(
            "echo",
            "Echo text back.",
            {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
            echo,
        )
        logger = FakeLogger()
        provider = AnthropicProvider(
            config
            or {"id": "test", "type": "anthropic", "api_key": "x", "model": "fake-model"},
            registry,
            logger,
            max_iterations=max_iterations,
        )
        return provider, client, logger, registry, executed

    return _make


def _user_tool_result_messages(call_kwargs):
    return [
        message
        for message in call_kwargs["messages"]
        if message.get("role") == "user" and isinstance(message.get("content"), list)
    ]


def test_tool_use_then_text(make_provider):
    provider, client, _logger, _registry, executed = make_provider(
        [
            FakeResponse([tool_use_block(tool_input={"text": "hi"})]),
            FakeResponse([text_block("done")]),
        ]
    )

    result = provider.run("say hi", "system")

    assert result == "done"
    assert executed == ["hi"]
    assert client.messages.calls[0]["system"] == "system"
    assert client.messages.calls[0]["max_tokens"] == 4096
    assert client.messages.calls[0]["tools"][0]["name"] == "echo"

    second_messages = client.messages.calls[1]["messages"]
    assistant_messages = [m for m in second_messages if m.get("role") == "assistant"]
    assert assistant_messages[-1]["content"][0]["type"] == "tool_use"
    assert assistant_messages[-1]["content"][0]["id"] == "toolu_1"

    tool_result = _user_tool_result_messages(client.messages.calls[1])[-1]["content"][0]
    assert tool_result["type"] == "tool_result"
    assert tool_result["tool_use_id"] == "toolu_1"
    assert tool_result["is_error"] is False
    assert tool_result["content"] == "echo:hi"


def test_multiple_tool_uses_share_one_user_message(make_provider):
    provider, client, _logger, _registry, executed = make_provider(
        [
            FakeResponse(
                [
                    tool_use_block(tool_id="toolu_1", tool_input={"text": "a"}),
                    tool_use_block(tool_id="toolu_2", tool_input={"text": "b"}),
                ]
            ),
            FakeResponse([text_block("done")]),
        ]
    )

    result = provider.run("two tools", "system")

    assert result == "done"
    assert executed == ["a", "b"]

    result_messages = _user_tool_result_messages(client.messages.calls[1])
    assert len(result_messages) == 1
    assert [block["tool_use_id"] for block in result_messages[0]["content"]] == ["toolu_1", "toolu_2"]


def test_tool_error_sets_is_error(make_provider):
    provider, client, logger, registry, _executed = make_provider(
        [
            FakeResponse([tool_use_block(tool_id="toolu_1", name="explode", tool_input={})]),
            FakeResponse([text_block("recovered")]),
        ]
    )

    def explode():
        raise RuntimeError("boom")

    registry.register("explode", "Always fails.", {"type": "object", "properties": {}}, explode)

    result = provider.run("fail", "system")

    assert result == "recovered"
    tool_result = _user_tool_result_messages(client.messages.calls[1])[-1]["content"][0]
    assert tool_result["is_error"] is True
    assert "boom" in tool_result["content"]
    assert "tool_error" in [event_type for event_type, _payload in logger.events]


def test_no_text_after_tools_uses_summary(make_provider):
    provider, client, _logger, _registry, executed = make_provider(
        [
            FakeResponse([tool_use_block(tool_input={"text": "hi"})]),
            FakeResponse([]),
        ]
    )

    result = provider.run("say hi", "system")

    assert result.startswith("Actions completed:")
    assert "echo" in result
    assert executed == ["hi"]
    assert len(client.messages.calls) == 2


def test_text_tool_call_fallback(make_provider):
    provider, client, _logger, _registry, executed = make_provider(
        [
            FakeResponse([text_block('{"tool": "echo", "arguments": {"text": "hi"}}')]),
            FakeResponse([text_block("done")]),
        ]
    )

    result = provider.run("say hi", "system")

    assert result == "done"
    assert executed == ["hi"]
    assert "Tool `echo` returned" in client.messages.calls[1]["messages"][-1]["content"]


def test_refusal_stop_reason_is_reported(make_provider):
    provider, _client, _logger, _registry, _executed = make_provider(
        [FakeResponse([], stop_reason="refusal")]
    )

    result = provider.run("do something", "system")

    assert "refusal" in result


def test_iteration_cap_returns_summary_not_raw_json(make_provider):
    provider, _client, logger, _registry, executed = make_provider(
        [
            FakeResponse([tool_use_block(tool_id="t1", tool_input={"text": "a"})]),
            FakeResponse([tool_use_block(tool_id="t2", tool_input={"text": "b"})]),
        ],
        max_iterations=2,
    )

    result = provider.run("loop forever", "system")

    assert result.startswith("Actions completed:")
    assert "echo" in result
    assert "{" not in result
    assert executed == ["a", "b"]
    assert any(event == "iteration_limit" for event, _payload in logger.events)


def test_missing_api_key_raises(monkeypatch):
    monkeypatch.delenv("CLOUD_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="API key"):
        AnthropicProvider(
            {"id": "cloud_anthropic", "type": "anthropic", "api_key": "", "model": "m"},
            ToolRegistry(),
            FakeLogger(),
        )
