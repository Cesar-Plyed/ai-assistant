"""AIEngine must bind a turn to the chat id captured when it starts, even if the
provider (or the UI switching chats mid-turn) mutates engine.chat_id."""

import core.ai_engine
from core.ai_engine import AIEngine
from tests.fakes import FakeLogger


class FakeProvider:
    def __init__(self, engine, new_chat_id):
        self.engine = engine
        self.new_chat_id = new_chat_id
        self.cancel_event = None

    def run(self, prompt, system_instruction):
        self.engine.chat_id = self.new_chat_id
        return "ok"


def test_process_message_uses_captured_chat_id(monkeypatch):
    engine = AIEngine(chat_id="chat_a")
    engine.logger = FakeLogger()

    loads = []
    saves = []
    monkeypatch.setattr(core.ai_engine, "load_chat", lambda chat_id: loads.append(chat_id) or [])
    monkeypatch.setattr(
        core.ai_engine, "save_chat", lambda chat_id, prompt, response: saves.append(chat_id)
    )
    monkeypatch.setattr(engine, "get_provider_instance", lambda: FakeProvider(engine, "chat_b"))

    result = engine.process_message("hi")

    assert result == "ok"
    assert loads == ["chat_a"]
    assert saves == ["chat_a"]
    assert engine.chat_id == "chat_b"  # the mutation happened, but persistence used chat_a


def test_explicit_chat_id_wins_over_engine_state(monkeypatch):
    """The UI passes the worker's id explicitly, so a switch before run() starts
    cannot redirect the turn to the new chat."""
    engine = AIEngine(chat_id="chat_a")
    engine.logger = FakeLogger()

    loads = []
    saves = []
    monkeypatch.setattr(core.ai_engine, "load_chat", lambda chat_id: loads.append(chat_id) or [])
    monkeypatch.setattr(
        core.ai_engine, "save_chat", lambda chat_id, prompt, response: saves.append(chat_id)
    )
    monkeypatch.setattr(engine, "get_provider_instance", lambda: FakeProvider(engine, "chat_b"))

    engine.chat_id = "chat_b"  # switch happens before the worker starts
    result = engine.process_message("hi", chat_id="chat_a")

    assert result == "ok"
    assert loads == ["chat_a"]
    assert saves == ["chat_a"]


def test_use_history_false_skips_load_but_still_saves(monkeypatch):
    engine = AIEngine(chat_id="chat_a")
    engine.logger = FakeLogger()

    loads = []
    saves = []
    monkeypatch.setattr(core.ai_engine, "load_chat", lambda chat_id: loads.append(chat_id) or [])
    monkeypatch.setattr(
        core.ai_engine, "save_chat", lambda chat_id, prompt, response: saves.append(chat_id)
    )
    monkeypatch.setattr(engine, "get_provider_instance", lambda: FakeProvider(engine, "chat_b"))

    result = engine.process_message("hi", use_history=False)

    assert result == "ok"
    assert loads == []
    assert saves == ["chat_a"]
