"""Agent-loop behavior of the native Gemini provider, with a fake client.

No network is used: ``google.genai.Client`` is replaced before the provider is
instantiated, and the fake chat queues canned responses.
"""

from types import SimpleNamespace

from google import genai
from google.genai import types

from core.providers.gemini_provider import GeminiProvider
from core.tools import ToolRegistry
from tests.fakes import FakeLogger


class FakeChat:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def send_message(self, message):
        self.calls.append(message)
        if not self._responses:
            raise AssertionError("send_message called more times than expected")
        return self._responses.pop(0)


class FakeChats:
    def __init__(self, chat):
        self._chat = chat
        self.create_calls = []

    def create(self, **kwargs):
        self.create_calls.append(kwargs)
        return self._chat


class FakeClient:
    def __init__(self, chat):
        self.chats = FakeChats(chat)


class FakeMap:
    """Stand-in for google-genai's MapComposite/Struct wrappers."""

    def __init__(self, data):
        self._data = data

    def items(self):
        return self._data.items()


def install_fake_client(monkeypatch, responses):
    chat = FakeChat(responses)
    clients = []

    def factory(**kwargs):
        client = FakeClient(chat)
        clients.append(client)
        return client

    monkeypatch.setattr(genai, "Client", factory)
    return chat, clients


def make_provider(monkeypatch, responses, registry, max_iterations=8):
    chat, clients = install_fake_client(monkeypatch, responses)
    logger = FakeLogger()
    provider = GeminiProvider(
        {"id": "gemini_test", "api_key": "test-key", "model": "gemini-test"},
        registry,
        logger,
        max_iterations=max_iterations,
    )
    return provider, logger, chat, clients


def make_echo_registry():
    executed = []
    registry = ToolRegistry()

    def echo(text):
        executed.append(text)
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
    return registry, executed


def fake_response(text=None, function_calls=None):
    return SimpleNamespace(text=text, function_calls=function_calls)


def fake_call(name, args=None):
    return SimpleNamespace(name=name, args=args if args is not None else {})


def test_multiple_function_calls_are_sent_in_one_message(monkeypatch):
    registry, executed = make_echo_registry()
    provider, _logger, chat, _clients = make_provider(
        monkeypatch,
        [
            fake_response(
                function_calls=[
                    fake_call("echo", {"text": "one"}),
                    fake_call("echo", {"text": "two"}),
                ]
            ),
            fake_response(text="done"),
        ],
        registry,
    )

    assert provider.run("say hi", "system") == "done"
    assert executed == ["one", "two"]
    assert chat.calls[0] == "say hi"

    parts = chat.calls[1]
    assert isinstance(parts, list)
    assert len(parts) == 2
    assert all(isinstance(part, types.Part) for part in parts)
    assert [part.function_response.name for part in parts] == ["echo", "echo"]
    assert [part.function_response.response for part in parts] == [
        {"result": "echo:one"},
        {"result": "echo:two"},
    ]


def test_tool_error_is_logged_and_loop_recovers(monkeypatch):
    registry = ToolRegistry()

    def explode():
        raise RuntimeError("boom")

    registry.register(
        "explode",
        "Always fails.",
        {"type": "object", "properties": {}},
        explode,
    )
    provider, logger, _chat, _clients = make_provider(
        monkeypatch,
        [
            fake_response(function_calls=[fake_call("explode")]),
            fake_response(text="recovered"),
        ],
        registry,
    )

    assert provider.run("break it", "system") == "recovered"
    assert any(event == "tool_error" for event, _payload in logger.events)
    assert not any(event == "tool_result" for event, _payload in logger.events)


def test_nested_args_are_converted_to_plain_python(monkeypatch):
    received = []
    registry = ToolRegistry()

    def capture(**kwargs):
        received.append(kwargs)
        return "captured"

    registry.register(
        "capture",
        "Capture arguments.",
        {"type": "object", "properties": {}},
        capture,
    )
    nested_args = FakeMap(
        {
            "text": "hi",
            "nested": FakeMap({"inner": [FakeMap({"value": 1})]}),
        }
    )
    provider, _logger, _chat, _clients = make_provider(
        monkeypatch,
        [
            fake_response(function_calls=[fake_call("capture", nested_args)]),
            fake_response(text="done"),
        ],
        registry,
    )

    assert provider.run("capture", "system") == "done"
    assert len(received) == 1

    arguments = received[0]
    assert isinstance(arguments, dict)
    assert arguments == {"text": "hi", "nested": {"inner": [{"value": 1}]}}
    assert isinstance(arguments["nested"], dict)
    assert isinstance(arguments["nested"]["inner"], list)
    assert isinstance(arguments["nested"]["inner"][0], dict)


def test_text_tool_call_fallback(monkeypatch):
    registry, executed = make_echo_registry()
    provider, _logger, chat, _clients = make_provider(
        monkeypatch,
        [
            fake_response(text='```json\n{"tool": "echo", "arguments": {"text": "hi"}}\n```'),
            fake_response(text="done"),
        ],
        registry,
    )

    assert provider.run("fallback", "system") == "done"
    assert executed == ["hi"]

    follow_up = chat.calls[1]
    assert isinstance(follow_up, str)
    assert "Tool `echo` returned" in follow_up
    assert "echo:hi" in follow_up


def test_no_text_after_tools_uses_summary(monkeypatch):
    registry, executed = make_echo_registry()
    provider, _logger, chat, _clients = make_provider(
        monkeypatch,
        [
            fake_response(function_calls=[fake_call("echo", {"text": "hi"})]),
            fake_response(text=None),
        ],
        registry,
    )

    result = provider.run("summary", "system")

    assert result.startswith("Actions completed:")
    assert "echo" in result
    assert executed == ["hi"]
    assert len(chat.calls) == 2


def test_answer_on_the_last_allowed_iteration_is_returned(monkeypatch):
    registry, executed = make_echo_registry()
    provider, _logger, chat, _clients = make_provider(
        monkeypatch,
        [
            fake_response(function_calls=[fake_call("echo", {"text": "hi"})]),
            fake_response(text="FINAL ANSWER"),
        ],
        registry,
        max_iterations=2,
    )

    assert provider.run("loop", "system") == "FINAL ANSWER"
    assert executed == ["hi"]
    assert len(chat.calls) == 2


def test_iteration_cap_returns_summary_not_raw_json(monkeypatch):
    registry, executed = make_echo_registry()
    provider, logger, chat, _clients = make_provider(
        monkeypatch,
        [
            fake_response(function_calls=[fake_call("echo", {"text": "a"})]),
            fake_response(function_calls=[fake_call("echo", {"text": "b"})]),
        ],
        registry,
        max_iterations=2,
    )

    result = provider.run("loop forever", "system")

    assert result.startswith("Actions completed:")
    assert "{" not in result
    assert executed == ["a", "b"]
    assert len(chat.calls) == 2
    assert any(event == "iteration_limit" for event, _payload in logger.events)


def test_text_tool_call_at_the_cap_returns_summary(monkeypatch):
    registry, executed = make_echo_registry()
    provider, _logger, chat, _clients = make_provider(
        monkeypatch,
        [
            fake_response(text='{"tool": "echo", "arguments": {"text": "a"}}'),
            fake_response(text='{"tool": "echo", "arguments": {"text": "b"}}'),
        ],
        registry,
        max_iterations=2,
    )

    result = provider.run("loop", "system")

    assert result.startswith("Actions completed:")
    assert "{" not in result
    assert executed == ["a", "b"]
    assert len(chat.calls) == 2
