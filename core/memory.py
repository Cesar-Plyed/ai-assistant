import json
import threading
from pathlib import Path
from typing import Dict, List, Any, Union
from datetime import datetime

CHATS_DIR = Path("data/chats")
CHATS_DIR.mkdir(parents=True, exist_ok=True)

_lock = threading.RLock()

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
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            stored = str(data.get("id", ""))
        except Exception:
            stored = file_path.stem
        if sanitize_chat_id(stored) == safe:
            return file_path
    return None

def sanitize_chat_id(chat_id: str) -> str:
    return "".join(c for c in chat_id if c.isalnum() or c in ("_", "-"))


def get_chat_path(chat_id: str) -> Path:
    return CHATS_DIR / f"{sanitize_chat_id(chat_id)}.json"


def load_chat(chat_id: str) -> List[Dict[str, Any]]:
    path = get_chat_path(chat_id)
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("messages", [])
    except Exception as e:
        print(f"[memory] Could not read {path}: {e}")
        return []


def save_chat(chat_id, arg2: Union[List[Dict[str, Any]], str], arg3: str = None) -> None:
    safe_id = sanitize_chat_id(chat_id)
    path = CHATS_DIR / f"{safe_id}.json"
    with _lock:
        if isinstance(arg2, list):
            messages = arg2
        elif isinstance(arg2, str) and isinstance(arg3, str):
            messages = load_chat(safe_id)
            messages.append({"role": "user", "content": arg2})
            messages.append({"role": "assistant", "content": arg3})
        else:
            messages = load_chat(safe_id)

        payload = {
            "id": safe_id,
            "last_updated": datetime.now().isoformat(),
            "messages": messages,
        }
        tmp = path.parent / (path.name + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        tmp.replace(path)  # atomic on same filesystem


def list_chats() -> List[Dict[str, Any]]:
    with _lock:
        chats = []
        for file_path in CHATS_DIR.glob("*.json"):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                safe_id = sanitize_chat_id(data.get("id") or file_path.stem) or file_path.stem
                chats.append({
                    "id": safe_id,
                    "message_count": len(data.get("messages", [])),
                    "last_updated": data.get("last_updated"),
                })
            except Exception:
                continue
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


def rename_chat(old_id: str, new_id: str) -> bool:
    old_safe = sanitize_chat_id(old_id)
    new_safe = sanitize_chat_id(new_id)
    if not new_safe:
        return False
    if old_safe == new_safe:
        return True
    with _lock:
        old_path = CHATS_DIR / f"{old_safe}.json"
        new_path = CHATS_DIR / f"{new_safe}.json"
        if new_path.exists():
            return False
        try:
            messages = load_chat(old_safe) if old_path.exists() else []
            save_chat(new_safe, messages)
            if old_path.exists():
                old_path.unlink()
            return True
        except Exception as e:
            print(f"[memory] rename failed: {e}")
            return False