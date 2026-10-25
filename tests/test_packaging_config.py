"""Packaging/config regressions: PySide6-only, uv-managed, no requirements.txt."""

import re
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

ROOT = Path(__file__).resolve().parents[1]


def test_pyproject_uses_pyside6_and_uv():
    with open(ROOT / "pyproject.toml", "rb") as f:
        data = tomllib.load(f)

    dependencies = data["project"]["dependencies"]
    assert any(re.match(r"PySide6\b", dep) for dep in dependencies)
    assert data["project"]["scripts"]["ai-desktop-assistant"] == "main:main"
    assert not (ROOT / "requirements.txt").exists()


def test_no_pyqt6_references():
    forbidden = ["PyQt6", "pyqtSignal"]
    files = [ROOT / "config.py", ROOT / "main.py"]
    files += sorted((ROOT / "core").rglob("*.py"))
    files += sorted((ROOT / "ui").rglob("*.py"))

    hits = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            if token in text:
                hits.append(f"{path.relative_to(ROOT)}: {token}")

    assert not hits, f"PyQt6 references remain: {hits}"
