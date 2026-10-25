"""Build provider-specific multimodal user content from numbered attachments.

Images are sent in index order so "compare image 1 with image 2" is unambiguous.
Each image is preceded by a short text label (``Image #n``). The *model-ready*
derived image is used, never the original.
"""

from __future__ import annotations

import base64
from typing import Any

from core import attachments as att_mod


def _ordered_images(attachments: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    imgs = att_mod.image_attachments(attachments or [])
    return sorted(imgs, key=lambda a: a.get("index", 0))


def openai_user_content(text: str, attachments: list[dict[str, Any]] | None) -> Any:
    """``str`` when there are no images, else a list of text/``image_url`` parts."""
    images = _ordered_images(attachments)
    if not images:
        return text
    parts: list[dict[str, Any]] = [{"type": "text", "text": text}]
    for a in images:
        data, mime = att_mod.load_model_image(a)
        b64 = base64.b64encode(data).decode("ascii")
        parts.append({"type": "text", "text": f"Image #{a.get('index')}:"})
        parts.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})
    return parts


def anthropic_user_content(text: str, attachments: list[dict[str, Any]] | None) -> Any:
    images = _ordered_images(attachments)
    if not images:
        return text
    blocks: list[dict[str, Any]] = []
    for a in images:
        data, mime = att_mod.load_model_image(a)
        blocks.append({"type": "text", "text": f"Image #{a.get('index')}:"})
        blocks.append({"type": "image", "source": {
            "type": "base64", "media_type": mime,
            "data": base64.b64encode(data).decode("ascii")}})
    blocks.append({"type": "text", "text": text})
    return blocks


def gemini_parts(text: str, attachments: list[dict[str, Any]] | None) -> Any:
    """``str`` without images, else ``[Part, ...]`` using ``Part.from_bytes``."""
    images = _ordered_images(attachments)
    if not images:
        return text
    from google.genai import types

    parts: list[Any] = []
    for a in images:
        data, mime = att_mod.load_model_image(a)
        parts.append(types.Part.from_text(text=f"Image #{a.get('index')}:"))
        parts.append(types.Part.from_bytes(data=data, mime_type=mime))
    parts.append(types.Part.from_text(text=text))
    return parts


def clean_history(history: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Strip UI-only keys (attachments metadata); keep role/content only.

    By default only the *current* turn's images are sent; earlier attachments
    stay in history as their text manifest (already part of the stored content).
    """
    cleaned = []
    for msg in history or []:
        role = msg.get("role")
        if role not in ("user", "assistant", "system"):
            continue
        content = msg.get("content", "")
        atts = msg.get("attachments")
        if role == "user" and atts:
            manifest = att_mod.build_manifest(atts, vision=True)
            content = f"{content}\n\n{manifest}" if content else manifest
        cleaned.append({"role": role, "content": content})
    return cleaned
