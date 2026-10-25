import json
import threading
from pathlib import Path
from typing import Dict, List, Any, Union
from datetime import datetime

import config

CHATS_DIR = config.BASE_DIR / "data/chats"
CHATS_DIR.mkdir(parents=True, exist_ok=True)

_lock = threading.RLock()


def _read_chat_file(path: Path) -> dict | None:
    """Read a chat JSON file, returning None if it is missing or invalid."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _write_chat_atomic(path: Path, data: dict) -> None:
    """Write a chat JSON file through a temp file + atomic replace."""
    tmp = path.parent / (path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def _find_chat_file(chat_id: str) -> Path | None:
    """Locate a chat file by sanitized id, raw id, or the id stored inside the JSON."""
    safe = sanitize_chat_id(chat_id)
    direct = CHATS_DIR / f"{safe}.json"
    if direct.exists():
        return direct
    # Fall back: scan for any file whose stored id or stem matches.
    for file_path in CHATS_DIR.glob("*.json"):
        if file_path.stem == safe:
            return file_path
        data = _read_chat_file(file_path)
        stored = str(data.get("id", "")) if data else file_path.stem
        if sanitize_chat_id(stored) == safe:
            return file_path
    return None


def sanitize_chat_id(chat_id: str) -> str:
    return "".join(c for c in chat_id if c.isalnum() or c in ("_", "-"))


def get_chat_path(chat_id: str) -> Path:
    return CHATS_DIR / f"{sanitize_chat_id(chat_id)}.json"


def get_chat_title(chat_id: str) -> str | None:
    """Return the stored title for a chat, or None if it has none / cannot be read."""
    path = get_chat_path(chat_id)
    if not path.exists():
        path = _find_chat_file(chat_id)
    if path is None:
        return None
    data = _read_chat_file(path)
    if data is None:
        return None
    title = data.get("title")
    return title if isinstance(title, str) else None


def set_chat_title(chat_id: str, title: str) -> bool:
    """Set or update a chat title without touching its messages or identity.

    The chat must already exist: titles are metadata, so this never recreates a
    chat that was deleted while a title request was in flight.
    """
    safe_id = sanitize_chat_id(chat_id)
    if not safe_id:
        return False
    with _lock:
        path = get_chat_path(safe_id)
        if not path.exists():
            path = _find_chat_file(safe_id)
        if path is None:
            return False
        data = _read_chat_file(path)
        if data is None:
            return False
        data["id"] = data.get("id") or safe_id
        data.setdefault("messages", [])
        data.setdefault("last_updated", datetime.now().isoformat())
        data["title"] = title
        try:
            _write_chat_atomic(path, data)
            return True
        except Exception as e:
            print(f"[memory] set title failed for '{chat_id}': {e}")
            return False


def load_chat(chat_id: str) -> List[Dict[str, Any]]:
    path = get_chat_path(chat_id)
    if not path.exists():
        return []
    data = _read_chat_file(path)
    if data is None:
        print(f"[memory] Could not read {path}")
        return []
    messages = data.get("messages", [])
    return messages if isinstance(messages, list) else []


def save_chat(chat_id, arg2: Union[List[Dict[str, Any]], str], arg3: str = None,
              attachments: List[Dict[str, Any]] | None = None) -> None:
    safe_id = sanitize_chat_id(chat_id)
    path = get_chat_path(safe_id)
    with _lock:
        existing = _read_chat_file(path) or {}
        existing_messages = existing.get("messages", [])
        if not isinstance(existing_messages, list):
            existing_messages = []

        if isinstance(arg2, list):
            messages = arg2
        elif isinstance(arg2, str) and isinstance(arg3, str):
            messages = list(existing_messages)
            user_msg: Dict[str, Any] = {"role": "user", "content": arg2}
            if attachments:
                # Metadata only (id, kind, path, mime, size, w/h, sha256, index): no base64.
                from core.attachments import public_metadata

                user_msg["attachments"] = [public_metadata(a) for a in attachments]
            messages.append(user_msg)
            messages.append({"role": "assistant", "content": arg3})
        else:
            messages = list(existing_messages)

        payload = {
            "id": safe_id,
            "last_updated": datetime.now().isoformat(),
            "messages": messages,
        }
        existing_title = existing.get("title")
        if isinstance(existing_title, str):
            payload["title"] = existing_title
        _write_chat_atomic(path, payload)


def list_chats() -> List[Dict[str, Any]]:
    with _lock:
        chats = []
        for file_path in CHATS_DIR.glob("*.json"):
            data = _read_chat_file(file_path)
            if data is None:
                continue
            safe_id = sanitize_chat_id(data.get("id") or file_path.stem) or file_path.stem
            chats.append({
                "id": safe_id,
                "title": data.get("title"),
                "message_count": len(data.get("messages", [])),
                "last_updated": data.get("last_updated"),
            })
    chats.sort(key=lambda x: x.get("last_updated") or "", reverse=True)
    return chats


def delete_chat(chat_id: str) -> bool:
    with _lock:
        path = _find_chat_file(chat_id)
        if path is None:
            return False
        try:
            path.unlink()
            return True
        except Exception as e:
            print(f"[memory] delete failed for '{chat_id}': {e}")
            return False
