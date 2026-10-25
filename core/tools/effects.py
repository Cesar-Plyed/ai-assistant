"""Side-effect metadata for tools.

After a tool succeeds, :func:`describe_effect` returns a ``(title, description)``
pair the UI shows as a toast (e.g. ``("Archivos", "Se escribió informe.md")``).
Read-only tools have no effect and produce no toast.
"""

from __future__ import annotations

import os
from typing import Any

MAX_LEN = 80


def _base(path: Any) -> str:
    return os.path.basename(str(path or "").rstrip("/\\")) or str(path or "")


def _short(text: Any) -> str:
    text = str(text or "")
    return text if len(text) <= MAX_LEN else text[: MAX_LEN - 1] + "…"


# tool name -> (title, builder(args) -> description)
_EFFECTS: dict[str, tuple[str, Any]] = {
    "write_text_file": ("Archivos", lambda a: f"Se escribió {_base(a.get('file_path'))}"),
    "import_uploaded_file": ("Archivos", lambda a: f"Se importó {_base(a.get('source_path'))}"),
    "browser_goto": ("Navegador", lambda a: f"Se abrió {_short(a.get('url'))}"),
    "browser_click": ("Navegador", lambda a: "Se hizo clic en un elemento"),
    "browser_fill": ("Navegador", lambda a: "Se rellenó un campo"),
    "browser_close": ("Navegador", lambda a: "Se cerró el navegador"),
    "open_application": ("Aplicación", lambda a: f"Se abrió {_short(a.get('app_name'))}"),
    "run_console_command": ("Sistema", lambda a: f"Se ejecutó: {_short(a.get('command'))}"),
    "click_mouse": ("Control", lambda a: "Se hizo clic con el mouse"),
    "type_text": ("Control", lambda a: "Se escribió texto con el teclado"),
}


def describe_effect(name: str, arguments: dict[str, Any] | None) -> tuple[str, str] | None:
    args = arguments if isinstance(arguments, dict) else {}
    if name.startswith("mcp__"):
        parts = name.split("__", 2)
        label = ".".join(parts[1:]) if len(parts) == 3 else name
        return ("MCP", f"Se ejecutó {_short(label)}")
    spec = _EFFECTS.get(name)
    if spec is None:
        return None
    title, builder = spec
    try:
        return title, builder(args)
    except Exception:
        return title, "Acción completada"
