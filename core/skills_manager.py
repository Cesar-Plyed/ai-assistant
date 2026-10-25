"""Skills 2.0 — folders of instructions (and optionally tools) under ``skills/``.

Canonical layout::

    skills/<id>/
      SKILL.md        YAML frontmatter + instruction body
      skill.py        optional: register(registry)
      references/     docs loaded on demand
      scripts/        optional, must be declared in the frontmatter

Discovery only reads frontmatter and **never imports code**. The body of a
skill enters the model context only when it is activated (``@skill-id`` in the
prompt, or the ``load_skill`` tool). Code in ``skill.py`` is imported only for
skills the user enabled in Settings.

Legacy ``skill.json`` skills still work (with a warning) and can be migrated
with :func:`migrate_legacy_skill`.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import shutil
import stat
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import yaml

import config

MAX_BODY_LINES = 500
MAX_BODY_TOKENS = 5000          # estimated as chars / 4
MAX_SKILL_BYTES = 10 * 1024 * 1024
MAX_SKILL_FILE_BYTES = 2 * 1024 * 1024
MAX_SKILL_FILES = 200
SKILL_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$", re.IGNORECASE)
_ABS_PATH_RE = re.compile(
    r"(?<![\w.])(?:/(?:home|usr|etc|var|opt|root|mnt|tmp|Users)/|[A-Za-z]:\\\\|~/)"
)
_FIRST_SECOND_PERSON = re.compile(r"^\s*(i|we|you|my|your|use this to|helps you)\b", re.IGNORECASE)
_REF_RE = re.compile(r"references/[\w./-]+")
_MENTION_RE = re.compile(r"(?:(?<=\s)|^)@([A-Za-z0-9][A-Za-z0-9_-]*)")


# ── Data ─────────────────────────────────────────────────────────────────
@dataclass
class SkillIssue:
    level: str   # "error" | "warning"
    message: str

    def __str__(self) -> str:
        return f"{self.level}: {self.message}"


@dataclass
class SkillInfo:
    id: str
    name: str
    description: str = ""
    version: str = "0.0.0"
    tags: list[str] = field(default_factory=list)
    allowed_tools: list[str] = field(default_factory=list)
    read_only: bool = False
    scripts: list[str] = field(default_factory=list)
    path: str = ""
    enabled: bool = False
    legacy: bool = False
    has_code: bool = False
    issues: list[SkillIssue] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not any(i.level == "error" for i in self.issues)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "name": self.name, "description": self.description,
            "version": self.version, "tags": list(self.tags),
            "allowed_tools": list(self.allowed_tools), "read_only": self.read_only,
            "path": self.path, "enabled": self.enabled, "legacy": self.legacy,
            "has_code": self.has_code, "valid": self.valid,
            "issues": [str(i) for i in self.issues],
        }

    def __getitem__(self, key: str) -> Any:   # dict-style access for old callers
        return self.as_dict()[key]


def _skills_dir() -> Path:
    return Path(config.SKILLS_DIR)


# ── SKILL.md parsing ─────────────────────────────────────────────────────
def split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Return ``(frontmatter_dict, body)``. Raises ``ValueError`` if malformed."""
    text = text.lstrip("\ufeff")
    if not text.startswith("---"):
        raise ValueError("SKILL.md must start with a '---' YAML frontmatter block.")
    lines = text.splitlines()
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        raise ValueError("Frontmatter block is not closed with '---'.")
    try:
        data = yaml.safe_load("\n".join(lines[1:end])) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML frontmatter: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("Frontmatter must be a YAML mapping.")
    body = "\n".join(lines[end + 1:]).lstrip("\n")
    return data, body


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [v.strip() for v in value.split(",") if v.strip()]
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()]
    return []


def _info_from_frontmatter(skill_id: str, path: Path, meta: dict[str, Any]) -> SkillInfo:
    return SkillInfo(
        id=skill_id,
        name=str(meta.get("name") or skill_id),
        description=str(meta.get("description") or "").strip(),
        version=str(meta.get("version") or "0.0.0"),
        tags=_as_list(meta.get("tags")),
        allowed_tools=_as_list(meta.get("allowed-tools", meta.get("allowed_tools"))),
        read_only=bool(meta.get("read-only", meta.get("read_only", False))),
        scripts=_as_list(meta.get("scripts")),
        path=str(path),
        has_code=(path / "skill.py").exists(),
    )


# ── Validation ───────────────────────────────────────────────────────────
def validate_skill(path: str | Path, known_tools: set[str] | None = None) -> list[SkillIssue]:
    """Static checks; never imports or executes anything from the skill."""
    root = Path(path)
    issues: list[SkillIssue] = []

    def err(msg: str) -> None:
        issues.append(SkillIssue("error", msg))

    def warn(msg: str) -> None:
        issues.append(SkillIssue("warning", msg))

    md = root / "SKILL.md"
    if not md.exists():
        if (root / "skill.json").exists():
            warn("Legacy skill.json format: migrate to SKILL.md (Skills → Migrate).")
            return issues
        err("Missing SKILL.md.")
        return issues
    try:
        meta, body = split_frontmatter(md.read_text(encoding="utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        err(str(exc))
        return issues

    for key in ("name", "description"):
        if not str(meta.get(key) or "").strip():
            err(f"Frontmatter field '{key}' is required.")
    description = str(meta.get("description") or "")
    if description and _FIRST_SECOND_PERSON.match(description):
        warn("Description should be written in the third person "
             "(e.g. 'Guides the assistant to …').")
    if len(description) > 1024:
        warn("Description is longer than 1024 characters.")

    lines = body.count("\n") + 1 if body else 0
    if lines > MAX_BODY_LINES:
        err(f"Body has {lines} lines (limit {MAX_BODY_LINES}); move detail to references/.")
    tokens = len(body) // 4
    if tokens > MAX_BODY_TOKENS:
        err(f"Body is ~{tokens} tokens (limit ~{MAX_BODY_TOKENS}); move detail to references/.")

    for ref in sorted(set(_REF_RE.findall(body))):
        ref = ref.rstrip(".,;:)")
        if not (root / ref).is_file():
            err(f"Referenced file does not exist: {ref}")
    if _ABS_PATH_RE.search(body):
        err("Body contains an absolute path; use paths relative to the skill folder.")

    scripts_dir = root / "scripts"
    declared = {Path(s).as_posix() for s in _as_list(meta.get("scripts"))}
    if scripts_dir.is_dir():
        for f in sorted(p for p in scripts_dir.rglob("*") if p.is_file()):
            rel = f.relative_to(root).as_posix()
            if rel not in declared and f.name not in declared:
                err(f"Script not declared in frontmatter 'scripts': {rel}")
    for d in declared:
        if not (root / d).is_file():
            err(f"Declared script does not exist: {d}")

    if ((root / "skill.py").exists() and meta.get("read-only", meta.get("read_only")) is True
            and not _as_list(meta.get("allowed-tools", meta.get("allowed_tools")))):
        warn("Skill is marked read-only but ships skill.py; its tools are not part of the "
             "read-only profile unless they are listed in 'allowed-tools'.")
    if known_tools is not None:
        for tool in _as_list(meta.get("allowed-tools", meta.get("allowed_tools"))):
            if tool not in known_tools:
                warn(f"allowed-tools lists an unknown tool: {tool}")

    for p in root.rglob("*"):
        if p.is_symlink():
            err(f"Symlinks are not allowed: {p.relative_to(root)}")
    return issues


# ── Discovery ────────────────────────────────────────────────────────────
def _enabled_ids() -> set[str]:
    return set(config.SETTINGS.get("enabled_skills", []))


def _read_legacy(entry: Path) -> SkillInfo:
    try:
        manifest = json.loads((entry / "skill.json").read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            manifest = {}
    except Exception:
        manifest = {}
    return SkillInfo(
        id=entry.name,
        name=str(manifest.get("name", entry.name)),
        description=str(manifest.get("description", "")),
        version=str(manifest.get("version", "0.0")),
        path=str(entry),
        legacy=True,
        has_code=(entry / "skill.py").exists(),
        issues=[SkillIssue("warning", "Legacy skill.json format; migrate to SKILL.md.")],
    )


def discover_skills(validate: bool = True) -> list[SkillInfo]:
    """Metadata of every skill folder, enabled or not. Reads frontmatter only."""
    skills: list[SkillInfo] = []
    root = _skills_dir()
    if not root.exists():
        return skills
    enabled = _enabled_ids()
    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or entry.name.startswith((".", "_")):
            continue
        md = entry / "SKILL.md"
        if md.exists():
            try:
                meta, _body = split_frontmatter(md.read_text(encoding="utf-8"))
                info = _info_from_frontmatter(entry.name, entry, meta)
            except (ValueError, UnicodeDecodeError) as exc:
                info = SkillInfo(id=entry.name, name=entry.name, path=str(entry),
                                 issues=[SkillIssue("error", str(exc))])
            else:
                if validate:
                    info.issues = validate_skill(entry)
        elif (entry / "skill.json").exists():
            info = _read_legacy(entry)
        else:
            continue
        info.enabled = info.id in enabled
        skills.append(info)
    return skills


def get_skill(skill_id: str) -> SkillInfo | None:
    """Find a skill by folder id, falling back to its frontmatter ``name``."""
    skills = discover_skills()
    for skill in skills:
        if skill.id == skill_id:
            return skill
    for skill in skills:
        if skill.name == skill_id:
            return skill
    return None


def enabled_skills() -> list[SkillInfo]:
    return [s for s in discover_skills() if s.enabled and s.valid]


# ── Catalog / activation ─────────────────────────────────────────────────
def catalog_text() -> str:
    """Compact catalog (name + description + tags) of enabled skills for the system prompt."""
    skills = enabled_skills()
    if not skills:
        return ""
    lines = ["AVAILABLE SKILLS (instructions load on demand — call load_skill(name) "
             "when one is relevant, or the user may mention it as @skill-id):"]
    for s in skills:
        tags = f" [{', '.join(s.tags)}]" if s.tags else ""
        lines.append(f"- {s.id}: {s.description}{tags}")
    return "\n".join(lines)


def load_skill_body(skill_id: str) -> str:
    """Return the SKILL.md body (plus the allowed-tools note) for an enabled skill."""
    skill = get_skill(skill_id)
    if skill is None:
        return f"Error: skill '{skill_id}' not found."
    if not skill.enabled:
        return f"Error: skill '{skill_id}' is not enabled."
    if not skill.valid:
        return f"Error: skill '{skill_id}' failed validation: " + "; ".join(
            str(i) for i in skill.issues if i.level == "error")
    root = Path(skill.path)
    if skill.legacy:
        return f"{skill.description}\n(Legacy skill: provides tools only.)"
    _meta, body = split_frontmatter((root / "SKILL.md").read_text(encoding="utf-8"))
    header = [f"# Skill: {skill.name} (v{skill.version})"]
    if skill.allowed_tools:
        header.append("Allowed tools: " + ", ".join(skill.allowed_tools))
    if skill.read_only:
        header.append("This skill is read-only: do not modify files or system state.")
    refs = sorted(p.relative_to(root).as_posix() for p in (root / "references").glob("**/*")
                  if p.is_file()) if (root / "references").is_dir() else []
    if refs:
        header.append("References (read with read_skill_reference): " + ", ".join(refs))
    return "\n".join(header) + "\n\n" + body


def read_skill_reference(skill_id: str, ref_path: str) -> str:
    skill = get_skill(skill_id)
    if skill is None or not skill.enabled:
        return f"Error: skill '{skill_id}' is not available."
    root = (Path(skill.path) / "references").resolve()
    try:
        target = (root / ref_path.removeprefix("references/")).resolve()
        target.relative_to(root)
    except (ValueError, OSError):
        return "Error: reference path must stay inside the skill's references/ folder."
    if not target.is_file():
        return f"Error: reference '{ref_path}' not found in skill '{skill_id}'."
    if target.stat().st_size > MAX_SKILL_FILE_BYTES:
        return "Error: reference file is too large."
    return target.read_text(encoding="utf-8", errors="replace")


def mentioned_skill_ids(prompt: str) -> list[str]:
    """Enabled skill ids mentioned as ``@skill-id`` in a prompt (order kept)."""
    enabled = {s.id for s in enabled_skills()}
    found: list[str] = []
    for match in _MENTION_RE.finditer(prompt or ""):
        sid = match.group(1)
        if sid in enabled and sid not in found:
            found.append(sid)
    return found


def activated_skills_text(skill_ids: list[str]) -> str:
    """Bodies of the skills activated for *this turn only*."""
    parts = [load_skill_body(sid) for sid in skill_ids]
    parts = [p for p in parts if not p.startswith("Error:")]
    if not parts:
        return ""
    return "ACTIVATED SKILLS (requested by the user for this message):\n\n" + "\n\n---\n\n".join(parts)


# ── Tools: load_skill / read_skill_reference + skill code ────────────────
SKILL_TOOL_NAMES = ("load_skill", "read_skill_reference")


def register_skill_tools(registry) -> None:
    """Register ``load_skill`` and ``read_skill_reference`` (only if skills are enabled)."""
    for name in SKILL_TOOL_NAMES:
        registry.unregister(name)
    if not enabled_skills():
        return
    registry.register(
        name="load_skill",
        description="Load the full instructions of an enabled skill by its id. "
                    "Use it when the task matches a skill in the catalog.",
        parameters={"type": "object",
                    "properties": {"name": {"type": "string", "description": "Skill id."}},
                    "required": ["name"]},
        func=lambda name: load_skill_body(name),
    )
    registry.register(
        name="read_skill_reference",
        description="Read a document from a skill's references/ folder.",
        parameters={"type": "object",
                    "properties": {"name": {"type": "string", "description": "Skill id."},
                                   "path": {"type": "string",
                                            "description": "Path inside references/."}},
                    "required": ["name", "path"]},
        func=lambda name, path: read_skill_reference(name, path),
    )


def load_enabled_skills(registry) -> list[str]:
    """Import and register code of every enabled, valid skill. Returns loaded ids."""
    register_skill_tools(registry)
    loaded: list[str] = []
    skills = discover_skills()
    # Tools a read-only skill declares in allowed-tools stay available in the
    # "read-only" tool profile; everything else from skills/MCP is excluded.
    config.READ_ONLY_EXTRA_TOOLS.clear()
    for skill in skills:
        if skill.enabled and skill.valid and skill.read_only:
            config.READ_ONLY_EXTRA_TOOLS.update(skill.allowed_tools)
            config.READ_ONLY_EXTRA_TOOLS.update(SKILL_TOOL_NAMES)
    for skill in skills:
        if not skill.enabled or not skill.valid or not skill.has_code:
            continue
        skill_path = Path(skill.path) / "skill.py"
        try:
            spec = importlib.util.spec_from_file_location(f"skills.{skill.id}", skill_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            if hasattr(module, "register"):
                module.register(registry)
                loaded.append(skill.id)
        except Exception as e:
            print(f"[SkillsManager] Failed to load skill '{skill.id}': {e}")
    return loaded


# ── Legacy migration ─────────────────────────────────────────────────────
def migrate_legacy_skill(skill_id: str) -> str:
    """Create SKILL.md from a legacy skill.json (the json file is kept as backup)."""
    root = _skills_dir() / skill_id
    manifest_path = root / "skill.json"
    if (root / "SKILL.md").exists():
        return f"Skill '{skill_id}' already has a SKILL.md."
    if not manifest_path.exists():
        return f"Error: '{skill_id}' has no skill.json to migrate."
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return f"Error: invalid skill.json: {exc}"
    meta = {
        "name": skill_id,
        "description": str(manifest.get("description") or f"Provides the {skill_id} tools."),
        "version": str(manifest.get("version", "1.0.0")),
        "tags": [],
        "allowed-tools": [],
        "read-only": False,
    }
    front = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).strip()
    body = (f"# {manifest.get('name', skill_id)}\n\n"
            f"{manifest.get('description', '')}\n\n"
            "Migrated from skill.json. Edit this file to add guidance for the assistant.\n")
    (root / "SKILL.md").write_text(f"---\n{front}\n---\n\n{body}", encoding="utf-8")
    manifest_path.rename(root / "skill.json.bak")
    return f"Skill '{skill_id}' migrated to SKILL.md (skill.json kept as skill.json.bak)."


# ── Safe installation ────────────────────────────────────────────────────
def tree_sha256(root: Path) -> str:
    """Deterministic SHA-256 over relative paths and file contents."""
    digest = hashlib.sha256()
    for p in sorted(x for x in Path(root).rglob("*") if x.is_file()):
        digest.update(p.relative_to(root).as_posix().encode())
        digest.update(b"\0")
        digest.update(p.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _check_tree(root: Path) -> str | None:
    """Return an error message if the folder breaks install safety limits."""
    total, count = 0, 0
    for p in root.rglob("*"):
        if p.is_symlink():
            return f"Symlinks are not allowed ({p.relative_to(root)})."
        if p.is_file():
            count += 1
            size = p.stat().st_size
            total += size
            if size > MAX_SKILL_FILE_BYTES:
                return f"File too large: {p.relative_to(root)} ({size} bytes)."
    if count > MAX_SKILL_FILES:
        return f"Too many files ({count} > {MAX_SKILL_FILES})."
    if total > MAX_SKILL_BYTES:
        return f"Skill is too large ({total} bytes > {MAX_SKILL_BYTES})."
    return None


Confirm = Callable[[dict[str, Any]], bool]


def inspect_skill_folder(source: str | Path) -> dict[str, Any]:
    """Summary shown in the confirmation dialog (no code is executed)."""
    root = Path(source)
    info: SkillInfo | None = None
    if (root / "SKILL.md").exists():
        try:
            meta, _ = split_frontmatter((root / "SKILL.md").read_text(encoding="utf-8"))
            info = _info_from_frontmatter(root.name, root, meta)
        except (ValueError, UnicodeDecodeError):
            info = None
    elif (root / "skill.json").exists():
        info = _read_legacy(root)
    return {
        "id": root.name,
        "name": info.name if info else root.name,
        "description": info.description if info else "",
        "allowed_tools": info.allowed_tools if info else [],
        "read_only": info.read_only if info else False,
        "has_code": (root / "skill.py").exists(),
        "scripts": info.scripts if info else [],
        "sha256": tree_sha256(root),
        "issues": [str(i) for i in validate_skill(root)],
    }


def install_skill_from_folder(source_folder: str, confirm: Confirm | None = None) -> str:
    """Validate and copy a skill folder into ``skills/``.

    ``confirm`` receives :func:`inspect_skill_folder`'s summary (name, SHA-256,
    allowed tools, whether it ships code) and must return ``True`` to proceed.
    Without a callback the install is refused: nothing is copied silently.
    """
    source = Path(source_folder)
    if not source.is_dir():
        return f"Error: '{source_folder}' is not a directory."
    if not SKILL_ID_RE.match(source.name):
        return "Error: the skill folder name may only contain letters, digits, '-' and '_'."
    if not ((source / "SKILL.md").exists()
            or ((source / "skill.json").exists() and (source / "skill.py").exists())):
        return "Error: the folder must contain SKILL.md (or legacy skill.json + skill.py)."
    problem = _check_tree(source)
    if problem:
        return f"Error: {problem}"
    issues = validate_skill(source)
    errors = [i for i in issues if i.level == "error"]
    if errors:
        return "Error: skill failed validation: " + "; ".join(i.message for i in errors)

    summary = inspect_skill_folder(source)
    if confirm is None or not confirm(summary):
        return "Installation cancelled: confirmation is required."

    destination = _skills_dir() / source.name
    try:
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(source, destination, symlinks=False)
        (destination / ".install.json").write_text(json.dumps({
            "sha256": summary["sha256"],
            "installed_at": datetime.now().isoformat(timespec="seconds"),
        }), encoding="utf-8")
        return (f"Skill '{source.name}' installed (sha256 {summary['sha256'][:12]}…). "
                "Enable it from the Skills dialog to activate it.")
    except Exception as e:
        return f"Error installing skill: {e}"


def _safe_extract(zip_path: str, dest: Path) -> str | None:
    """Extract defensively. Returns an error message, or None on success."""
    dest = dest.resolve()
    total = 0
    with zipfile.ZipFile(zip_path) as zf:
        infos = zf.infolist()
        if len(infos) > MAX_SKILL_FILES * 2:
            return "Archive contains too many entries."
        for zi in infos:
            name = zi.filename
            if name.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", name) or "\\" in name:
                return f"Unsafe path in archive: {name}"
            mode = (zi.external_attr >> 16) & 0xFFFF
            if mode and stat.S_ISLNK(mode):
                return f"Symlink in archive is not allowed: {name}"
            target = (dest / name).resolve()
            try:
                target.relative_to(dest)
            except ValueError:
                return f"Archive entry escapes the target folder (zip-slip): {name}"
            total += zi.file_size
            if zi.file_size > MAX_SKILL_FILE_BYTES or total > MAX_SKILL_BYTES:
                return "Archive exceeds the size limit."
        for zi in infos:
            target = (dest / zi.filename).resolve()
            if zi.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(zi) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)
    return None


def install_skill_from_zip(zip_path: str, confirm: Confirm | None = None) -> str:
    """Extract a zipped skill into a temp dir (zip-slip safe), then install it."""
    if not zipfile.is_zipfile(zip_path):
        return f"Error: '{zip_path}' is not a valid zip file."
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        problem = _safe_extract(zip_path, tmp_path)
        if problem:
            return f"Error: {problem}"
        markers = ("SKILL.md", "skill.json")
        if any((tmp_path / m).exists() for m in markers):
            staged = tmp_path.parent / (Path(zip_path).stem or "skill")
            # Top-level skill: use the zip name as the folder name.
            holder = Path(tempfile.mkdtemp(dir=tmp))
            skill_root = holder / re.sub(r"[^A-Za-z0-9_-]", "-", staged.name)
            skill_root.mkdir()
            for item in list(tmp_path.iterdir()):
                if item != holder:
                    shutil.move(str(item), str(skill_root / item.name))
        else:
            candidates = [p for p in tmp_path.iterdir()
                          if p.is_dir() and any((p / m).exists() for m in markers)]
            if not candidates:
                return "Error: no SKILL.md found in the zip archive."
            skill_root = candidates[0]
        return install_skill_from_folder(str(skill_root), confirm=confirm)
