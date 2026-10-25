import io

import pytest
from PIL import Image

import config
from core import attachments as att
from core.providers import multimodal


@pytest.fixture(autouse=True)
def uploads(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "UPLOADS_DIR", tmp_path / "uploads")
    return tmp_path


def _png(size=(100, 60), color=(255, 0, 0), mode="RGB"):
    buf = io.BytesIO()
    Image.new(mode, size, color).save(buf, "PNG")
    return buf.getvalue()


def test_image_metadata_thumbnail_and_derived(uploads):
    meta = att.process_attachment_bytes(_png((3000, 2000)), "big.png", "chat1", 1)
    assert meta["kind"] == "image" and meta["width"] == 3000 and meta["index"] == 1
    assert len(meta["sha256"]) == 64
    assert max(meta["model_width"], meta["model_height"]) == att.MODEL_MAX_EDGE
    assert meta["model_mime"] == "image/jpeg"
    assert "uploads/chat1/" in meta["path"].replace("\\", "/")
    with Image.open(meta["model_path"]) as im:
        assert not im.getexif()


def test_alpha_png_keeps_png(uploads):
    meta = att.process_attachment_bytes(_png(mode="RGBA", color=(0, 0, 0, 10)), "a.png", "c", 1)
    assert meta["model_mime"] == "image/png"


def test_rejects_svg_and_magic_mismatch(uploads):
    with pytest.raises(att.AttachmentError):
        att.process_attachment_bytes(b"<svg xmlns='http://www.w3.org/2000/svg'></svg>", "x.png", "c")
    # Not an image by magic bytes -> stored as plain file, not decoded as image.
    meta = att.process_attachment_bytes(b"hello", "fake.png", "c")
    assert meta["kind"] == "file"


def test_rejects_animated_gif(uploads):
    buf = io.BytesIO()
    a, b = Image.new("RGB", (10, 10), "red"), Image.new("RGB", (10, 10), "blue")
    a.save(buf, "GIF", save_all=True, append_images=[b], duration=50)
    with pytest.raises(att.AttachmentError, match="Animated"):
        att.process_attachment_bytes(buf.getvalue(), "a.gif", "c")


def test_size_limits(uploads, monkeypatch):
    monkeypatch.setattr(att, "MAX_IMAGE_BYTES", 10)
    with pytest.raises(att.AttachmentError):
        att.process_attachment_bytes(_png(), "a.png", "c")


def test_pixel_limit(uploads, monkeypatch):
    monkeypatch.setattr(att, "MAX_IMAGE_PIXELS", 100)
    with pytest.raises(att.AttachmentError):
        att.process_attachment_bytes(_png((50, 50)), "a.png", "c")


def test_manifest_numbering_and_renumber(uploads):
    a = att.process_attachment_bytes(_png(), "one.png", "c", 1)
    f = att.process_attachment_bytes(b"data", "notes.txt", "c", 2)
    atts = att.renumber([f, a])
    assert [x["index"] for x in atts] == [1, 2]
    text = att.build_manifest(atts)
    assert "#1 file 'notes.txt'" in text and "#2 image 'one.png'" in text
    assert "no vision" in att.build_manifest([a], vision=False)


def test_openai_content_orders_images(uploads):
    a = att.process_attachment_bytes(_png(color=(1, 2, 3)), "a.png", "c", 2)
    b = att.process_attachment_bytes(_png(color=(9, 9, 9)), "b.png", "c", 1)
    parts = multimodal.openai_user_content("compara la imagen 1 con la 2", [a, b])
    labels = [p["text"] for p in parts if p["type"] == "text"][1:]
    assert labels == ["Image #1:", "Image #2:"]
    urls = [p for p in parts if p["type"] == "image_url"]
    assert len(urls) == 2 and urls[0]["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_anthropic_content_blocks(uploads):
    a = att.process_attachment_bytes(_png(), "a.png", "c", 1)
    blocks = multimodal.anthropic_user_content("hi", [a])
    assert blocks[1]["type"] == "image" and blocks[1]["source"]["type"] == "base64"
    assert blocks[-1] == {"type": "text", "text": "hi"}


def test_no_images_returns_plain_text():
    assert multimodal.openai_user_content("x", []) == "x"
    assert multimodal.anthropic_user_content("x", None) == "x"


def test_history_has_no_base64_and_keeps_manifest(uploads, chats_dir):
    from core import memory

    a = att.process_attachment_bytes(_png(), "a.png", "c", 1)
    memory.save_chat("c1", "mira", "ok", attachments=[a])
    stored = memory.load_chat("c1")[0]
    assert "data:image" not in str(stored) and "/9j/" not in str(stored) and stored["attachments"][0]["index"] == 1
    cleaned = multimodal.clean_history(memory.load_chat("c1"))
    assert "#1 image 'a.png'" in cleaned[0]["content"]
    assert set(cleaned[0]) == {"role", "content"}
