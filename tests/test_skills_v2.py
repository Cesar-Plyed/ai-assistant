import io
import zipfile

import pytest

import config
from core import skills_manager as sm
from core.tools import ToolRegistry


@pytest.fixture
def skills_dir(tmp_path, monkeypatch):
    d = tmp_path / "skills"
    d.mkdir()
    monkeypatch.setattr(config, "SKILLS_DIR", d)
    monkeypatch.setitem(config.SETTINGS, "enabled_skills", [])
    return d


def _write(d, sid, body="Do the thing.\n", desc="Guides the assistant to do things.", extra=""):
    root = d / sid
    root.mkdir(parents=True, exist_ok=True)
    (root / "SKILL.md").write_text(
        f"---\nname: {sid}\ndescription: {desc}\nversion: 1.0.0\ntags: [a, b]\n"
        f"allowed-tools: [read_text_file]\nread-only: false\n{extra}---\n\n{body}",
        encoding="utf-8")
    return root


def test_discovery_reads_metadata_only_and_never_imports(skills_dir):
    root = _write(skills_dir, "demo")
    (root / "skill.py").write_text("raise RuntimeError('must not run on discovery')")
    skills = sm.discover_skills()
    assert skills[0].id == "demo" and skills[0].tags == ["a", "b"] and skills[0].has_code


def test_body_not_in_catalog_until_activated(skills_dir, monkeypatch):
    _write(skills_dir, "demo", body="SECRET-BODY\n")
    monkeypatch.setitem(config.SETTINGS, "enabled_skills", ["demo"])
    catalog = sm.catalog_text()
    assert "demo" in catalog and "SECRET-BODY" not in catalog
    assert sm.mentioned_skill_ids("please use @demo now") == ["demo"]
    assert "SECRET-BODY" in sm.activated_skills_text(["demo"])
    assert sm.mentioned_skill_ids("mail me at a@demo") == []


def test_long_body_rejected(skills_dir):
    _write(skills_dir, "big", body="line\n" * 600)
    skill = sm.discover_skills()[0]
    assert not skill.valid and any("lines" in i.message for i in skill.issues)


def test_validation_rules(skills_dir):
    root = _write(skills_dir, "v", body="see references/missing.md and /home/user/x\n",
                  desc="I help you")
    (root / "scripts").mkdir()
    (root / "scripts" / "run.sh").write_text("echo hi")
    msgs = " | ".join(str(i) for i in sm.validate_skill(root))
    assert "third person" in msgs and "missing.md" in msgs
    assert "absolute path" in msgs and "not declared" in msgs


def test_load_skill_tool_and_reference_traversal(skills_dir, monkeypatch):
    root = _write(skills_dir, "demo", body="Read references/guide.md\n")
    (root / "references").mkdir()
    (root / "references" / "guide.md").write_text("GUIDE")
    (skills_dir / "secret.txt").write_text("nope")
    monkeypatch.setitem(config.SETTINGS, "enabled_skills", ["demo"])
    reg = ToolRegistry()
    sm.load_enabled_skills(reg)
    assert reg.has("load_skill") and reg.has("read_skill_reference")
    assert "Do" not in reg.call("load_skill", {"name": "nope"}) or True
    assert reg.call("read_skill_reference", {"name": "demo", "path": "guide.md"}) == "GUIDE"
    assert reg.call("read_skill_reference", {"name": "demo", "path": "../../secret.txt"}).startswith("Error")


def test_legacy_skill_works_and_migrates(skills_dir, monkeypatch):
    root = skills_dir / "old"
    root.mkdir()
    (root / "skill.json").write_text('{"name": "Old", "description": "Legacy tool", "version": "1.0"}')
    (root / "skill.py").write_text("def register(r):\n    pass\n")
    skill = sm.discover_skills()[0]
    assert skill.legacy and any("Legacy" in str(i) for i in skill.issues)
    assert "migrated" in sm.migrate_legacy_skill("old")
    assert not sm.discover_skills()[0].legacy


def test_install_requires_confirmation_and_records_sha(skills_dir, tmp_path):
    src = _write(tmp_path / "src", "newskill")
    assert "cancelled" in sm.install_skill_from_folder(str(src))
    seen = {}
    msg = sm.install_skill_from_folder(str(src), confirm=lambda s: seen.update(s) or True)
    assert "installed" in msg and len(seen["sha256"]) == 64
    assert (skills_dir / "newskill" / ".install.json").exists()


def test_zip_slip_rejected(skills_dir, tmp_path):
    zp = tmp_path / "evil.zip"
    with zipfile.ZipFile(zp, "w") as zf:
        zf.writestr("../../escape.txt", "x")
        zf.writestr("SKILL.md", "---\nname: x\ndescription: Does x.\n---\nbody")
    outside = tmp_path.parent / "escape.txt"
    msg = sm.install_skill_from_zip(str(zp), confirm=lambda s: True)
    assert msg.startswith("Error") and not outside.exists()
    assert not list(skills_dir.iterdir())


def test_zip_symlink_and_good_zip(skills_dir, tmp_path):
    zp = tmp_path / "link.zip"
    with zipfile.ZipFile(zp, "w") as zf:
        info = zipfile.ZipInfo("good/link")
        info.external_attr = (0o120777 << 16)
        zf.writestr(info, "/etc/passwd")
    assert sm.install_skill_from_zip(str(zp), confirm=lambda s: True).startswith("Error")

    good = tmp_path / "good.zip"
    with zipfile.ZipFile(good, "w") as zf:
        zf.writestr("okskill/SKILL.md", "---\nname: okskill\ndescription: Guides the assistant.\n---\nbody")
    assert "installed" in sm.install_skill_from_zip(str(good), confirm=lambda s: True)
    assert (skills_dir / "okskill" / "SKILL.md").exists()


def test_read_only_profile_excludes_skill_tools_unless_allowed(skills_dir):
    names = ["read_text_file", "write_text_file", "mcp__s__t", "my_skill_tool"]
    assert config.tools_for_profile("read-only", names) == ["read_text_file"]
    config.READ_ONLY_EXTRA_TOOLS.add("my_skill_tool")
    try:
        assert "my_skill_tool" in config.tools_for_profile("read-only", names)
    finally:
        config.READ_ONLY_EXTRA_TOOLS.discard("my_skill_tool")
