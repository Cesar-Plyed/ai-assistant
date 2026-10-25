"""Agent-loop behavior of the OpenAI-compatible provider, with a fake client."""

from types import SimpleNamespace

from core.providers.openai_compatible_provider import OpenAICompatibleProvider
from core.tools import ToolRegistry
from tests.fakes import FakeLogger


class FakeFunction:
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments


class FakeToolCall:
    def __init__(self, call_id, name, arguments):
        self.id = call_id
        self.function = FakeFunction(name, arguments)


class FakeMessage:
    def __init__(self, content, tool_calls=None, refusal=None):
        self.content = content
        self.tool_calls = tool_calls
        self.refusal = refusal

    def model_dump(self, exclude_none=True):
        data = {
            "role": "assistant",
            "content": self.content,
            "refusal": self.refusal,
        }
        if self.tool_calls is not None:
            data["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.function.name,
                        "arguments": call.function.arguments,
                    },
                }
                for call in self.tool_calls
            ]
        if exclude_none:
            data = {key: value for key, value in data.items() if value is not None}
        return data


class FakeResponse:
    def __init__(self, message):
        self.choices = [SimpleNamespace(message=message)]


class FakeClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return self._responses.pop(0)


def make_provider(responses, max_iterations=8):
    registry = ToolRegistry()
    executed = []

    def echo(text):
        executed.append(text)
        return f"echo:{text}"

    registry.register(
        "echo",
        "Echo text back.",
        {"type": "object", "properties": {"text": {"type": "string"}}},
        echo,
    )

    def boom():
        raise RuntimeError("kaboom")

    registry.register("boom", "Always fails.", {"type": "object", "properties": {}}, boom)

    provider = OpenAICompatibleProvider(
        {
            "id": "test",
            "base_url": "http://localhost:1/v1",
            "api_key": "x",
            "model": "fake",
        },
        registry,
        FakeLogger(),
        max_iterations=max_iterations,
    )
    client = FakeClient(responses)
    provider.client = client
    return provider, executed, client


def _tool_messages(call_kwargs):
    return [m for m in call_kwargs["messages"] if m.get("role") == "tool"]


def test_tool_call_then_text_returns_text():
    provider, executed, client = make_provider([
        FakeResponse(FakeMessage(None, [FakeToolCall("call_1", "echo", '{"text": "hi"}')])),
        FakeResponse(FakeMessage("done")),
    ])

    result = provider.run("say hi", "system")

    assert result == "done"
    assert executed == ["hi"]
    tool_messages = _tool_messages(client.calls[1])
    assert any(m.get("tool_call_id") == "call_1" for m in tool_messages)
    assistant_messages = [
        m for m in client.calls[1]["messages"] if m.get("role") == "assistant"
    ]
    assert assistant_messages == [
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "echo", "arguments": '{"text": "hi"}'},
                }
            ],
        }
    ]


def test_tools_without_final_text_does_not_crash():
    provider, executed, client = make_provider(
        [
            FakeResponse(FakeMessage(None, [FakeToolCall("call_1", "echo", '{"text": "a"}')])),
            FakeResponse(FakeMessage(None, [FakeToolCall("call_2", "echo", '{"text": "b"}')])),
        ],
        max_iterations=2,
    )

    result = provider.run("loop", "system")

    assert result.startswith("Actions completed:")
    assert "echo" in result
    assert executed == ["a", "b"]
    assert len(client.calls) == 2


def test_invalid_json_arguments_are_not_executed():
    provider, executed, client = make_provider([
        FakeResponse(FakeMessage(None, [FakeToolCall("call_1", "echo", "{bad")])),
        FakeResponse(FakeMessage("recovered")),
    ])

    result = provider.run("broken json", "system")

    assert result == "recovered"
    assert executed == []
    tool_messages = _tool_messages(client.calls[1])
    assert any("Invalid JSON arguments" in str(m.get("content")) for m in tool_messages)


def test_serialize_message_fallback_without_model_dump():
    message = SimpleNamespace(
        content="x",
        tool_calls=[FakeToolCall("call_1", "echo", '{"text": "hi"}')],
    )

    serialized = OpenAICompatibleProvider._serialize_message(message)

    assert serialized["role"] == "assistant"
    assert serialized["content"] == "x"
    assert serialized["tool_calls"][0]["id"] == "call_1"
    assert serialized["tool_calls"][0]["function"]["name"] == "echo"


def test_text_tool_call_fallback_executes_and_continues():
    text_call = '```json\n{"tool": "echo", "arguments": {"text": "hi"}}\n```'
    provider, executed, client = make_provider([
        FakeResponse(FakeMessage(text_call)),
        FakeResponse(FakeMessage("done")),
    ])

    result = provider.run("say hi", "system")

    assert result == "done"
    assert executed == ["hi"]
    second_messages = client.calls[1]["messages"]
    assert any(
        m.get("role") == "assistant" and m.get("content") == text_call
        for m in second_messages
    )
    assert any(
        m.get("role") == "user" and "Tool `echo` returned" in str(m.get("content"))
        for m in second_messages
    )


def test_plain_json_answer_is_not_executed():
    payload = '{"answer": 42}'
    provider, executed, client = make_provider([FakeResponse(FakeMessage(payload))])

    result = provider.run("what is the answer?", "system")

    assert result == payload
    assert executed == []
    assert len(client.calls) == 1


def test_multiple_native_tool_calls_in_one_response():
    provider, executed, client = make_provider([
        FakeResponse(FakeMessage(None, [
            FakeToolCall("call_1", "echo", '{"text": "a"}'),
            FakeToolCall("call_2", "echo", '{"text": "b"}'),
        ])),
        FakeResponse(FakeMessage("done")),
    ])

    result = provider.run("echo twice", "system")

    assert result == "done"
    assert executed == ["a", "b"]
    tool_messages = _tool_messages(client.calls[1])
    assert [m.get("tool_call_id") for m in tool_messages] == ["call_1", "call_2"]
    assert [m.get("content") for m in tool_messages] == ["echo:a", "echo:b"]


def test_tool_error_is_logged():
    provider, executed, client = make_provider([
        FakeResponse(FakeMessage(None, [FakeToolCall("call_1", "boom", "{}")])),
        FakeResponse(FakeMessage("recovered")),
    ])

    result = provider.run("boom", "system")

    assert result == "recovered"
    assert executed == []
    errors = [payload for event, payload in provider.logger.events if event == "tool_error"]
    assert errors
    assert errors[0]["name"] == "boom"
    assert "RuntimeError" in str(errors[0].get("error"))
    tool_messages = _tool_messages(client.calls[1])
    assert "RuntimeError" in str(tool_messages[0].get("content"))


def test_refusal_without_content_returns_refusal():
    provider, executed, client = make_provider([
        FakeResponse(FakeMessage(None, tool_calls=None, refusal="no puedo")),
    ])

    result = provider.run("do something", "system")

    assert result == "no puedo"
    assert executed == []
    assert len(client.calls) == 1
