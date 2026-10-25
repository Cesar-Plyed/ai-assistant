"""Chat persistence: titles are metadata and must never alter chat identity."""

from core import memory


def test_set_title_does_not_change_chat_id(chats_dir):
    memory.save_chat("chat_a", "hi", "hello")
    assert memory.set_chat_title("chat_a", "My_Title") is True

    assert (chats_dir / "chat_a.json").exists()
    assert memory.get_chat_title("chat_a") == "My_Title"
    assert len(memory.load_chat("chat_a")) == 2


def test_save_chat_preserves_title(chats_dir):
    memory.save_chat("chat_a", "hi", "hello")
    memory.set_chat_title("chat_a", "My_Title")
    memory.save_chat("chat_a", "again", "reply")

    assert memory.get_chat_title("chat_a") == "My_Title"
    assert len(memory.load_chat("chat_a")) == 4


def test_list_chats_includes_title(chats_dir):
    memory.save_chat("chat_a", "hi", "hello")
    memory.set_chat_title("chat_a", "My_Title")

    chats = {chat["id"]: chat for chat in memory.list_chats()}
    assert "chat_a" in chats
    assert chats["chat_a"]["title"] == "My_Title"


def test_set_title_missing_chat_returns_false(chats_dir):
    """A title request that arrives after the chat was deleted must not
    resurrect it as an empty ghost chat."""
    assert memory.set_chat_title("new_chat", "X") is False
    assert not (chats_dir / "new_chat.json").exists()


def test_get_title_missing_returns_none(chats_dir):
    assert memory.get_chat_title("does_not_exist") is None
