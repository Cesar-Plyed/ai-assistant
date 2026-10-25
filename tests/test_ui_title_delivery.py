"""MainWindow chat/title routing.

All memory access is faked so these tests never touch data/chats, and no
worker thread is ever started (title generation is stubbed out).
"""

import pytest

import ui.main_window as main_window_module
from core import memory


class FakeSignal:
    def __init__(self):
        self.slots = []

    def connect(self, slot):
        self.slots.append(slot)


class FakeTitleWorker:
    """Non-thread stand-in used to verify worker lifetime bookkeeping."""

    instances = []

    def __init__(self, engine, chat_id, prompt):
        self.chat_id = chat_id
        self.prompt = prompt
        self.started = False
        self.title_generated = FakeSignal()
        self.finished = FakeSignal()
        FakeTitleWorker.instances.append(self)

    def start(self):
        self.started = True

    def isRunning(self):
        return False

    def cancel(self):
        pass

    def wait(self, _timeout):
        pass

    def deleteLater(self):
        pass


class FakeAIWorker:
    """Non-thread stand-in so _send_message never starts a real request."""

    instances = []

    def __init__(self, engine, chat_id, prompt):
        self.chat_id = chat_id
        self.prompt = prompt
        self.response_ready = FakeSignal()
        self.error_occurred = FakeSignal()
        self.finished = FakeSignal()
        FakeAIWorker.instances.append(self)

    def start(self):
        pass

    def isRunning(self):
        return False


@pytest.fixture
def window(qtbot, monkeypatch):
    titles = []

    monkeypatch.setattr(memory, "load_chat", lambda chat_id: [])
    monkeypatch.setattr(memory, "list_chats", lambda: [])
    monkeypatch.setattr(memory, "get_chat_title", lambda chat_id: None)
    monkeypatch.setattr(
        memory,
        "set_chat_title",
        lambda chat_id, title: titles.append((chat_id, title)) or True,
    )

    from ui.main_window import MainWindow

    w = MainWindow(chat_id="chat_a")
    qtbot.addWidget(w)
    yield w, titles
    w.close()


def test_title_does_not_change_ids(window):
    w, titles = window

    w._on_title_generated("chat_a", "My_Title")

    assert w.chat_id == "chat_a"
    assert w.ai_engine.chat_id == "chat_a"
    assert w.history_widget.current_chat_id == "chat_a"
    assert ("chat_a", "My_Title") in titles


def test_title_for_other_chat_is_persisted_without_switching(window):
    w, titles = window

    w._on_title_generated("chat_b", "Other")

    assert w.chat_id == "chat_a"
    assert ("chat_b", "Other") in titles


def test_response_for_other_chat_is_not_dropped_silently(window, monkeypatch):
    w, _titles = window
    added = []
    monkeypatch.setattr(w, "_add_message", lambda sender, content: added.append((sender, content)))

    w._receive_response("chat_b", "text")

    assert not any(sender == "Assistant" for sender, _content in added)
    assert "chat_b" in w.statusBar().currentMessage()


def test_response_for_current_chat_adds_message(window, monkeypatch):
    w, _titles = window
    added = []
    monkeypatch.setattr(w, "_add_message", lambda sender, content: added.append((sender, content)))

    w._receive_response("chat_a", "ok")

    assert ("Assistant", "ok") in added


def test_pending_title_generated_after_response(window, monkeypatch):
    w, _titles = window
    generated = []
    monkeypatch.setattr(
        w,
        "_generate_auto_title",
        lambda prompt, chat_id: generated.append((prompt, chat_id)),
    )
    w._pending_titles["chat_a"] = "hello"

    w._receive_response("chat_a", "ok")

    assert generated == [("hello", "chat_a")]
    assert "chat_a" not in w._pending_titles


def test_pending_title_for_other_chat_uses_that_chat(window, monkeypatch):
    w, _titles = window
    generated = []
    added = []
    monkeypatch.setattr(
        w,
        "_generate_auto_title",
        lambda prompt, chat_id: generated.append((prompt, chat_id)),
    )
    monkeypatch.setattr(w, "_add_message", lambda sender, content: added.append((sender, content)))
    w._pending_titles["chat_b"] = "b prompt"

    w._receive_response("chat_b", "ok")

    assert generated == [("b prompt", "chat_b")]
    assert not any(sender == "Assistant" for sender, _content in added)


def test_send_message_defers_title(window, monkeypatch):
    w, _titles = window
    generated = []
    monkeypatch.setattr(w, "_generate_auto_title", lambda *args: generated.append(args))
    monkeypatch.setattr(main_window_module, "AIWorker", FakeAIWorker)
    w.is_first_message = True
    w.input_field.setPlainText("hello")

    w._send_message()

    assert w._pending_titles.get("chat_a") == "hello"
    assert generated == []


def test_multiple_title_workers_are_kept_alive(window, monkeypatch):
    w, _titles = window
    FakeTitleWorker.instances = []
    monkeypatch.setattr(main_window_module, "TitleWorker", FakeTitleWorker)

    w._generate_auto_title("one", "chat_a")
    w._generate_auto_title("two", "chat_b")

    assert len(FakeTitleWorker.instances) == 2
    assert all(worker.started for worker in FakeTitleWorker.instances)
    assert len(w._title_workers) == 2
