import io

import pytest
from PIL import Image
from PySide6.QtCore import Qt

import config
from core.mcp.mentions import extract_mcp_mentions, mentions_context
from core.tools.effects import describe_effect
from ui import theme
from ui.completion_popup import CompletionItem, filter_items, fuzzy_score


@pytest.mark.parametrize("name", ["dark", "light"])
def test_theme_text_contrast_is_AA(name):
    t = theme.THEMES[name]
    for fg in ("text", "muted", "error", "success", "warning", "primary"):
        assert theme.contrast_ratio(t[fg], t["bg"]) >= 4.5, (name, fg)
    assert theme.contrast_ratio(t["on_primary"], t["primary"]) >= 4.5


def test_resolve_theme_and_apply(qtbot):
    from PySide6.QtWidgets import QApplication

    assert theme.resolve_theme("light") == "light"
    assert theme.resolve_theme("bogus") == "dark"
    assert theme.resolve_theme("system") in ("dark", "light")
    app = QApplication.instance()
    assert theme.apply_theme(app, "light") == "light"
    assert theme.tokens()["bg"] == theme.LIGHT["bg"] and "#f5f6fa" in app.styleSheet()
    theme.apply_theme(app, "dark")


def test_no_local_stylesheet_constants_left():
    import pathlib
    for f in pathlib.Path("ui").glob("*.py"):
        text = f.read_text()
        assert "Tokyo Night palette" not in text, f
        assert "#1a1b26" not in text or f.name == "theme.py", f


def test_fuzzy_filter_ranks_prefix_first():
    items = [CompletionItem("/export", "/export"), CompletionItem("/help", "/help"),
             CompletionItem("/clear", "/clear")]
    assert [i.title for i in filter_items(items, "cl")] == ["/clear"]
    assert fuzzy_score("ep", "export") is not None and fuzzy_score("zz", "export") is None
    assert [i.title for i in filter_items(items, "")] == ["/export", "/help", "/clear"]


def test_tool_effects():
    assert describe_effect("write_text_file", {"file_path": "/a/b/informe.md"}) == (
        "Archivos", "Se escribió informe.md")
    assert describe_effect("browser_goto", {"url": "https://x.dev"})[0] == "Navegador"
    assert describe_effect("open_application", {"app_name": "Firefox"}) == (
        "Aplicación", "Se abrió Firefox")
    assert describe_effect("mcp__srv__tool", {})[0] == "MCP"
    assert describe_effect("read_text_file", {"file_path": "x"}) is None


class _Tool:
    def __init__(self, mention, q):
        self.mention, self.qualified_name = mention, q


class _Mgr:
    def list_tools(self):
        return [_Tool("fs.read", "mcp__fs__read")]


def test_mcp_mentions_with_json_args():
    found = extract_mcp_mentions('use ;fs.read {"path": "a.txt"} please', _Mgr())
    assert found[0][1] == {"path": "a.txt"}
    assert "mcp__fs__read" in mentions_context(found)
    assert extract_mcp_mentions("a;fs.read", _Mgr()) == []
    assert extract_mcp_mentions(";nope.tool", _Mgr()) == []


def test_empty_mcp_message_in_popup(qtbot):
    from ui.chat_input import ChatInput

    w = ChatInput()
    qtbot.addWidget(w)
    w.resize(500, 120)
    w.show()
    w.set_tool_candidates([], "No hay servidores MCP configurados")
    qtbot.keyClicks(w, ";")
    popup = w._popup
    assert popup is not None and popup.count() == 1
    assert "No hay servidores MCP" in popup.item(0).text()
    assert not (popup.item(0).flags() & Qt.ItemFlag.ItemIsEnabled)


def test_tray_numbering_reorder_and_limit(qtbot, tmp_path, monkeypatch):
    from ui.attachment_tray import AttachmentTray

    monkeypatch.setattr(config, "UPLOADS_DIR", tmp_path / "up")
    tray = AttachmentTray(lambda: "chat")
    qtbot.addWidget(tray)
    reasons = []
    tray.rejected.connect(reasons.append)

    def png(color):
        buf = io.BytesIO()
        Image.new("RGB", (40, 40), color).save(buf, "PNG")
        return buf.getvalue()

    assert tray.add_image_bytes(png("red"), "a.png") and tray.add_image_bytes(png("blue"), "b.png")
    assert [m["index"] for m in tray.items] == [1, 2]
    first_id = tray.items[0]["id"]
    tray.move(0, 1)
    assert tray.items[1]["id"] == first_id and [m["index"] for m in tray.items] == [1, 2]
    tray.remove_at(0)
    assert len(tray.items) == 1 and tray.items[0]["index"] == 1
    for _ in range(12):
        tray.add_image_bytes(png("green"), "g.png")
    assert len(tray.items) == 10 and reasons
    taken = tray.take()
    assert len(taken) == 10 and tray.items == [] and tray.isHidden()


def test_window_toasts_for_tool_effect_and_theme_switch(qtbot, chats_dir):
    from ui.main_window import MainWindow

    w = MainWindow("t_ux")
    qtbot.addWidget(w)
    w.show()
    before = len(w.toast_manager._toasts)
    w._on_engine_event({"type": "tool_effect",
                        "payload": {"title": "Archivos", "description": "Se escribió informe.md"}})
    assert len(w.toast_manager._toasts) == before + 1
    toast = w.toast_manager._toasts[-1]
    assert toast.title_label.text() == "Archivos" and "informe.md" in toast.label.text()
    w._on_engine_event({"type": "attachments_skipped", "payload": {}})
    assert w.toast_manager._toasts[-1].level == "warning"
    w.close()


def test_composer_grows_up_to_half_the_window(qtbot, chats_dir):
    from PySide6.QtWidgets import QSizePolicy

    from ui.main_window import MainWindow

    w = MainWindow("t_layout")
    qtbot.addWidget(w)
    w.resize(1000, 700)
    w.show()
    qtbot.wait(20)

    # Compact: [attach][field][send] share one row.
    assert not w.input_field.is_expanded()
    assert w.attach_button.geometry().top() < w.input_field.geometry().bottom()
    assert w.send_button.geometry().top() < w.input_field.geometry().bottom()
    assert w.send_button.geometry().bottom() == w.input_field.geometry().bottom()
    compact_width = w.input_field.width()
    chat_height = w.chat_display.height()
    composer_top = w.composer.geometry().top()

    # A line wider than the compact field becomes a floating panel with the
    # buttons below it, at the corners.
    w.input_field.setPlainText("word " * 60)
    qtbot.wait(20)
    assert w.input_field.is_expanded()
    assert w.input_field.width() > compact_width
    assert w.attach_button.geometry().top() >= w.input_field.geometry().bottom()
    assert w.send_button.geometry().top() >= w.input_field.geometry().bottom()
    assert w.attach_button.geometry().left() == w.input_field.geometry().left()
    assert w.send_button.geometry().right() == w.input_field.geometry().right()

    assert w.input_field._max_height == 350
    w.input_field.setPlainText("\n".join(f"line {i}" for i in range(80)))
    qtbot.wait(20)
    assert w.input_field.height() == 350

    # The composer floats over the conversation instead of shrinking it.
    assert w.chat_display.height() == chat_height
    assert w.composer.geometry().top() < composer_top
    assert w.composer.geometry().bottom() == w.chat_display.geometry().bottom()

    # Buttons keep their width.
    for button in (w.attach_button, w.send_button):
        assert button.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Fixed

    # Deleting the text brings the compact row back.
    w.input_field.setPlainText("short")
    qtbot.wait(20)
    assert not w.input_field.is_expanded()
    assert w.send_button.geometry().bottom() == w.input_field.geometry().bottom()
    w.close()
