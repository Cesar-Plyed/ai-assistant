"""Inline autocomplete behaviour of :class:`ui.chat_input.ChatInput`."""

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent, QTextCursor

from ui.chat_input import ChatInput


@pytest.fixture
def chat_input(qtbot):
    widget = ChatInput()
    qtbot.addWidget(widget)
    widget.resize(640, 140)
    widget.show()
    yield widget
    widget.close()


def _press(widget, key):
    event = QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier)
    return widget.handle_completion_key(event)


def _popup(widget):
    popup = widget._popup
    assert popup is not None, "completion popup was never created"
    return popup


def test_at_shows_all_files_and_filters_as_text_is_typed(chat_input, qtbot):
    chat_input.set_file_candidates(["src/main.py", "README.md", "notes.txt"])

    qtbot.keyClicks(chat_input, "hello @")

    popup = _popup(chat_input)
    assert not popup.isHidden()
    assert popup.count() == 3

    qtbot.keyClicks(chat_input, "rea")

    assert popup.count() == 1
    assert popup.item(0).text() == "@README.md"


def test_enter_accepts_highlighted_file(chat_input, qtbot):
    chat_input.set_file_candidates(["src/main.py", "README.md"])
    qtbot.keyClicks(chat_input, "@")
    popup = _popup(chat_input)

    assert _press(chat_input, Qt.Key.Key_Down) is True
    assert popup.currentRow() == 1
    assert _press(chat_input, Qt.Key.Key_Return) is True

    assert chat_input.toPlainText() == "@README.md "
    assert chat_input.textCursor().position() == len("@README.md ")
    assert popup.isHidden()


def test_tab_accepts_command(chat_input, qtbot):
    chat_input.set_command_candidates(
        [
            ("/clear", "Clear the chat history shown in this window"),
            ("/help", "Show commands, mentions and tips"),
        ]
    )
    qtbot.keyClicks(chat_input, "/cl")

    popup = _popup(chat_input)
    assert popup.count() == 1
    assert popup.item(0).text() == "/clear  —  Clear the chat history shown in this window"

    assert _press(chat_input, Qt.Key.Key_Tab) is True
    assert chat_input.toPlainText() == "/clear "
    assert popup.isHidden()


def test_escape_hides_popup_and_other_keys_are_not_consumed(chat_input, qtbot):
    chat_input.set_file_candidates(["notes.txt"])
    qtbot.keyClicks(chat_input, "@")
    popup = _popup(chat_input)
    assert not popup.isHidden()

    assert _press(chat_input, Qt.Key.Key_Escape) is True
    assert popup.isHidden()

    assert _press(chat_input, Qt.Key.Key_A) is False
    assert _press(chat_input, Qt.Key.Key_Return) is False


def test_up_down_moves_selection_with_wrap_around(chat_input, qtbot):
    chat_input.set_file_candidates(["a.txt", "b.txt", "c.txt"])
    qtbot.keyClicks(chat_input, "@")
    popup = _popup(chat_input)
    assert popup.currentRow() == 0

    assert _press(chat_input, Qt.Key.Key_Down) is True
    assert popup.currentRow() == 1
    assert _press(chat_input, Qt.Key.Key_Down) is True
    assert popup.currentRow() == 2
    assert _press(chat_input, Qt.Key.Key_Down) is True
    assert popup.currentRow() == 0
    assert _press(chat_input, Qt.Key.Key_Up) is True
    assert popup.currentRow() == 2


def test_files_requested_once_per_trigger_occurrence(chat_input, qtbot):
    requested = []
    chat_input.filesRequested.connect(lambda: requested.append(True))

    qtbot.keyClicks(chat_input, "@")
    qtbot.keyClicks(chat_input, "rea")

    assert requested == [True]
    assert chat_input._popup is None or chat_input._popup.isHidden()

    # The window answers the signal: the popup appears without another keypress.
    chat_input.set_file_candidates(["README.md"])
    popup = _popup(chat_input)
    assert not popup.isHidden()
    assert popup.count() == 1


def test_tools_requested_once_per_trigger_occurrence(chat_input, qtbot):
    requested = []
    chat_input.toolsRequested.connect(lambda: requested.append(True))

    qtbot.keyClicks(chat_input, ";")
    qtbot.keyClicks(chat_input, "fi")

    assert requested == [True]
    assert chat_input._popup is None or chat_input._popup.isHidden()

    chat_input.set_tool_candidates([("filesystem.read_file", "Read a file")])
    popup = _popup(chat_input)
    assert not popup.isHidden()
    assert popup.item(0).text() == ";filesystem.read_file  —  Read a file"

    assert _press(chat_input, Qt.Key.Key_Enter) is True
    assert chat_input.toPlainText() == ";filesystem.read_file "


def test_trigger_inside_word_does_not_open_popup(chat_input, qtbot):
    requested = []
    chat_input.filesRequested.connect(lambda: requested.append(True))
    chat_input.set_file_candidates(["bar.txt"])

    qtbot.keyClicks(chat_input, "foo@bar")

    assert chat_input._popup is None or chat_input._popup.isHidden()
    assert requested == []


def test_path_with_spaces_is_inserted_quoted(chat_input, qtbot):
    chat_input.set_file_candidates(["my file.txt"])
    qtbot.keyClicks(chat_input, "@")

    assert _press(chat_input, Qt.Key.Key_Return) is True

    assert chat_input.toPlainText() == '@"my file.txt" '


def test_plain_text_round_trip_without_trigger(chat_input, qtbot):
    chat_input.setPlainText("hello world")
    assert chat_input.toPlainText() == "hello world"

    chat_input.moveCursor(QTextCursor.MoveOperation.End)
    qtbot.keyClicks(chat_input, "!")
    assert chat_input.toPlainText() == "hello world!"
    assert chat_input._popup is None or chat_input._popup.isHidden()


def test_height_grows_with_content_and_stops_at_the_limit(chat_input, qtbot):
    chat_input.set_height_limits(52, 160)
    assert chat_input.height() == 52

    chat_input.setPlainText("\n".join(f"line {i}" for i in range(4)))
    qtbot.wait(10)
    grown = chat_input.height()
    assert 52 < grown < 160

    chat_input.setPlainText("\n".join(f"line {i}" for i in range(40)))
    qtbot.wait(10)
    assert chat_input.height() == 160

    chat_input.setPlainText("short")
    qtbot.wait(10)
    assert chat_input.height() == 52
