from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

from core.version import __version__

ROOT = Path(__file__).resolve().parent.parent


def test_version_matches_pyproject_and_changelog():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert data["project"]["version"] == __version__
    assert f"## [{__version__}]" in (ROOT / "CHANGELOG.md").read_text()


def test_docs_exist():
    for name in ("ARCHITECTURE", "PROVIDERS", "SKILLS", "MCP", "TOOL_CALLING", "ATTACHMENTS",
                 "DESIGN_SYSTEM", "RELEASE", "SECURITY"):
        assert (ROOT / "docs" / f"{name}.md").is_file(), name
    assert list((ROOT / "docs" / "adr").glob("*.md"))
