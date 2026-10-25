"""Attachment processing: validation, storage, thumbnails and model-ready images.

Originals are copied to ``workspace/uploads/<chat_id>/<uuid>_<name>``. For
images a thumbnail (for the UI) and a *derived* copy for the model are written
next to it: max 1568 px on the long edge, JPEG q85 (PNG when there is alpha),
EXIF/metadata stripped. Chat messages store **metadata only** (never base64).
"""

from __future__ import annotations

import hashlib
import mimetypes
import re
import shutil
import uuid
from pathlib import Path
from typing import Any

import config

MAX_ATTACHMENTS = 10
MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_IMAGE_PIXELS = 50_000_000
MODEL_MAX_EDGE = 1568
THUMB_SIZE = 72

_IMAGE_MAGIC: list[tuple[bytes, str, str]] = [
    (b"\x89PNG\r\n\x1a\n", "png", "image/png"),
    (b"\xff\xd8\xff", "jpeg", "image/jpeg"),
    (b"GIF87a", "gif", "image/gif"),
    (b"GIF89a", "gif", "image/gif"),
]


class AttachmentError(ValueError):
    """User-presentable reason an attachment was rejected."""


def detect_image(data: bytes) -> tuple[str, str] | None:
    """Return ``(format, mime)`` from magic bytes, or ``None`` if not a raster image."""
    head = data[:16]
    for magic, fmt, mime in _IMAGE_MAGIC:
        if head.startswith(magic):
            return fmt, mime
    if head[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp", "image/webp"
    return None


def _looks_like_svg(data: bytes) -> bool:
    sample = data[:2048].lstrip().lower()
    return sample.startswith(b"<svg") or (sample.startswith((b"<?xml", b"<!doctype svg"))
                                          and b"<svg" in data[:4096].lower())


def safe_filename(name: str) -> str:
    name = Path(name).name or "file"
    name = re.sub(r"[^\w.\- ]", "_", name).strip(" .") or "file"
    return name[:120]


def _chat_dir(chat_id: str) -> Path:
    from core.memory import sanitize_chat_id

    safe = sanitize_chat_id(chat_id) or "default"
    d = Path(config.UPLOADS_DIR) / safe
    d.mkdir(parents=True, exist_ok=True)
    return d


def human_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{n} B"


def process_attachment_bytes(data: bytes, name: str, chat_id: str, index: int = 1) -> dict[str, Any]:
    """Validate, store and describe one attachment. Raises :class:`AttachmentError`."""
    if not data:
        raise AttachmentError(f"'{name}' is empty.")
    if _looks_like_svg(data):
        raise AttachmentError("SVG images are not supported.")

    detected = detect_image(data)
    kind = "image" if detected else "file"
    limit = MAX_IMAGE_BYTES if kind == "image" else MAX_FILE_BYTES
    if len(data) > limit:
        raise AttachmentError(
            f"'{name}' is {human_size(len(data))}; the limit is {human_size(limit)}."
        )

    att_id = uuid.uuid4().hex
    fname = safe_filename(name)
    directory = _chat_dir(chat_id)
    path = directory / f"{att_id}_{fname}"
    meta: dict[str, Any] = {
        "id": att_id,
        "kind": kind,
        "name": fname,
        "path": str(path),
        "mime": detected[1] if detected else (mimetypes.guess_type(fname)[0]
                                              or "application/octet-stream"),
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "index": index,
    }

    if kind == "image":
        try:
            _process_image(data, detected[0], path, directory, att_id, meta)
        except AttachmentError:
            _cleanup(directory, att_id)
            raise
        except Exception as exc:
            _cleanup(directory, att_id)
            raise AttachmentError(f"'{name}' is not a valid image ({exc}).") from exc
    else:
        path.write_bytes(data)
    return meta


def _cleanup(directory: Path, att_id: str) -> None:
    for p in directory.glob(f"{att_id}*"):
        try:
            p.unlink()
        except OSError:
            pass


def _process_image(data: bytes, fmt: str, path: Path, directory: Path,
                   att_id: str, meta: dict[str, Any]) -> None:
    import io

    from PIL import Image, ImageOps

    Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
    with Image.open(io.BytesIO(data)) as probe:
        w, h = probe.size
        if w * h > MAX_IMAGE_PIXELS:
            raise AttachmentError(f"Image is too large ({w}x{h} px).")
        if getattr(probe, "is_animated", False) and getattr(probe, "n_frames", 1) > 1:
            raise AttachmentError("Animated images are not supported.")
        probe.verify()

    path.write_bytes(data)
    with Image.open(io.BytesIO(data)) as img:
        img.load()
        img = ImageOps.exif_transpose(img)
        meta["width"], meta["height"] = img.size
        has_alpha = img.mode in ("RGBA", "LA") or "transparency" in img.info

        thumb = img.copy()
        thumb.thumbnail((THUMB_SIZE * 2, THUMB_SIZE * 2))
        thumb_path = directory / f"{att_id}_thumb.png"
        thumb.convert("RGBA").save(thumb_path, "PNG")
        meta["thumb"] = str(thumb_path)

        derived = img.copy()
        derived.thumbnail((MODEL_MAX_EDGE, MODEL_MAX_EDGE))
        if has_alpha:
            model_path = directory / f"{att_id}_model.png"
            derived.convert("RGBA").save(model_path, "PNG")
            meta["model_mime"] = "image/png"
        else:
            model_path = directory / f"{att_id}_model.jpg"
            derived.convert("RGB").save(model_path, "JPEG", quality=85)
            meta["model_mime"] = "image/jpeg"
        meta["model_path"] = str(model_path)
        meta["model_width"], meta["model_height"] = derived.size


def process_attachment(source: str | Path, chat_id: str, index: int = 1) -> dict[str, Any]:
    src = Path(source)
    if not src.is_file():
        raise AttachmentError(f"'{src.name}' is not a file.")
    size = src.stat().st_size
    if size > MAX_FILE_BYTES:
        raise AttachmentError(f"'{src.name}' is {human_size(size)}; the limit is "
                              f"{human_size(MAX_FILE_BYTES)}.")
    return process_attachment_bytes(src.read_bytes(), src.name, chat_id, index)


def renumber(attachments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Re-assign ``index`` 1..n in list order (after add/remove/reorder)."""
    for i, att in enumerate(attachments, start=1):
        att["index"] = i
    return attachments


def remove_attachment_files(att: dict[str, Any]) -> None:
    for key in ("path", "thumb", "model_path"):
        p = att.get(key)
        if p:
            try:
                Path(p).unlink()
            except OSError:
                pass


def image_attachments(attachments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [a for a in attachments if a.get("kind") == "image"]


def build_manifest(attachments: list[dict[str, Any]], vision: bool = True) -> str:
    """Numbered textual manifest so the user can say "compare image 1 with 2"."""
    if not attachments:
        return ""
    lines = ["[Attachments — refer to them by number]"]
    for att in sorted(attachments, key=lambda a: a.get("index", 0)):
        n = att.get("index", "?")
        if att["kind"] == "image":
            dims = f"{att.get('width', '?')}x{att.get('height', '?')}"
            note = "" if vision else " (image content not visible: model has no vision)"
            lines.append(f"#{n} image '{att['name']}' {dims}, {human_size(att['size'])}{note}")
        else:
            lines.append(f"#{n} file '{att['name']}', {human_size(att['size'])}, "
                         f"path: {att['path']} (read it with read_text_file)")
    return "\n".join(lines)


def load_model_image(att: dict[str, Any]) -> tuple[bytes, str]:
    """Bytes + mime of the derived (downscaled, metadata-free) image for the model."""
    p = att.get("model_path") or att.get("path")
    return Path(p).read_bytes(), att.get("model_mime") or att.get("mime", "image/jpeg")


def public_metadata(att: dict[str, Any]) -> dict[str, Any]:
    """What gets persisted in the chat file: metadata only, no pixel data."""
    keys = ("id", "kind", "name", "path", "mime", "size", "width", "height",
            "sha256", "index", "thumb", "model_path", "model_mime")
    return {k: att[k] for k in keys if k in att}


def copy_into_chat(src: Path, chat_id: str) -> Path:  # helper for tests/tools
    dst = _chat_dir(chat_id) / f"{uuid.uuid4().hex}_{safe_filename(src.name)}"
    shutil.copy2(src, dst)
    return dst
