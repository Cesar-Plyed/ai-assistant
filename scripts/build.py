#!/usr/bin/env python
"""Build a distributable app with PyInstaller for the current platform.

    uv sync --all-extras
    uv run python scripts/build.py

Output: ``dist/AI-Desktop-Assistant/`` (``--onedir``) or ``dist/AI Desktop Assistant.app``
on macOS, plus an archive (``.tar.gz`` / ``.zip``) and ``SHA256SUMS.txt``.
Chromium is *not* bundled: run ``playwright install chromium`` after installing.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.version import __version__  # noqa: E402

NAME = "AI-Desktop-Assistant"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    dist = ROOT / "dist"
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
           "--distpath", str(dist), "--workpath", str(ROOT / "build"),
           str(ROOT / "packaging" / "ai-desktop-assistant.spec")]
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True, cwd=ROOT)

    platform = {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")
    base = f"{NAME}-{__version__}-{platform}"
    archive: Path
    if sys.platform == "darwin":
        app = dist / "AI Desktop Assistant.app"
        archive = dist / f"{base}.zip"
        subprocess.run(["ditto", "-c", "-k", "--keepParent", str(app), str(archive)], check=True)
    elif sys.platform == "win32":
        archive = dist / f"{base}.zip"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in (dist / NAME).rglob("*"):
                zf.write(p, p.relative_to(dist))
    else:
        archive = dist / f"{base}.tar.gz"
        with tarfile.open(archive, "w:gz") as tf:
            tf.add(dist / NAME, arcname=NAME)

    sums = dist / f"SHA256SUMS-{platform}.txt"
    sums.write_text(f"{sha256(archive)}  {archive.name}\n", encoding="utf-8")
    print(f"built {archive} ({shutil.disk_usage(dist).used // 1_000_000} MB used in dist/)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
