"""
Skills are pluggable folders under skills/ that add extra tools to the
assistant without touching the core code.

Layout expected for each skill:

    skills/
      my_skill/
        skill.json   -> {"name": "...", "description": "...", "version": "1.0"}
        skill.py     -> defines register(registry) -> None, calling
                         registry.register(...) for each tool it provides.

Skills are only loaded if their id is listed in settings["enabled_skills"].
Installing a skill (copying/extracting a folder into skills/) does not
auto-enable it; the user turns it on from the Skills dialog, then the tool
registry is rebuilt.
"""

import importlib.util
import json
import shutil
from pathlib import Path
from typing import Any

import config
from config import SKILLS_DIR


def discover_skills() -> list[dict[str, Any]]:
    """Return metadata for every skill folder found under skills/, whether enabled or not."""
    skills = []
    if not SKILLS_DIR.exists():
        return skills

    for entry in sorted(SKILLS_DIR.iterdir()):
        if not entry.is_dir():
            continue
        manifest_path = entry / "skill.json"
        entry_point = entry / "skill.py"
        if not manifest_path.exists() or not entry_point.exists():
            continue
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
        except Exception:
            manifest = {}

        skills.append({
            "id": entry.name,
            "name": manifest.get("name", entry.name),
            "description": manifest.get("description", ""),
            "version": manifest.get("version", "0.0"),
            "enabled": entry.name in config.SETTINGS.get("enabled_skills", []),
            "path": str(entry),
        })
    return skills


def load_enabled_skills(registry) -> list[str]:
    """Import and register every skill listed in settings['enabled_skills']. Returns loaded skill ids."""
    loaded = []
    for skill in discover_skills():
        if not skill["enabled"]:
            continue
        skill_path = Path(skill["path"]) / "skill.py"
        try:
            spec = importlib.util.spec_from_file_location(f"skills.{skill['id']}", skill_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            if hasattr(module, "register"):
                module.register(registry)
                loaded.append(skill["id"])
        except Exception as e:
            print(f"[SkillsManager] Failed to load skill '{skill['id']}': {e}")
    return loaded


def install_skill_from_folder(source_folder: str) -> str:
    """Copy an external skill folder (containing skill.json + skill.py) into skills/."""
    source = Path(source_folder)
    if not source.is_dir():
        return f"Error: '{source_folder}' is not a directory."
    if not (source / "skill.json").exists() or not (source / "skill.py").exists():
        return "Error: the folder must contain both skill.json and skill.py."

    destination = SKILLS_DIR / source.name
    try:
        shutil.copytree(source, destination, dirs_exist_ok=True)
        return f"Skill '{source.name}' installed. Enable it from the Skills dialog to activate it."
    except Exception as e:
        return f"Error installing skill: {e}"


def install_skill_from_zip(zip_path: str) -> str:
    """Extract a zipped skill (containing skill.json + skill.py, possibly nested one level) into skills/."""
    import tempfile
    import zipfile

    if not zipfile.is_zipfile(zip_path):
        return f"Error: '{zip_path}' is not a valid zip file."

    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(tmp)

        tmp_path = Path(tmp)
        # Accept either skill.json at the top level, or inside a single nested folder.
        if (tmp_path / "skill.json").exists():
            skill_root = tmp_path
        else:
            candidates = [p for p in tmp_path.iterdir() if p.is_dir() and (p / "skill.json").exists()]
            if not candidates:
                return "Error: no skill.json found in the zip archive."
            skill_root = candidates[0]

        return install_skill_from_folder(str(skill_root))
