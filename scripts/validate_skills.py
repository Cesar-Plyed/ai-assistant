#!/usr/bin/env python
"""Validate skills: ``python scripts/validate_skills.py [skills_dir_or_skill_dir ...]``.

Exit code 1 if any skill has an error (warnings are printed but allowed).
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import skills_manager as sm  # noqa: E402


def _skill_dirs(arg: Path) -> list[Path]:
    if (arg / "SKILL.md").exists() or (arg / "skill.json").exists():
        return [arg]
    return sorted(p for p in arg.iterdir() if p.is_dir() and not p.name.startswith((".", "_")))


def main(argv: list[str]) -> int:
    targets = [Path(a) for a in argv] or [ROOT / "skills"]
    failed = False
    for target in targets:
        for skill_dir in _skill_dirs(target):
            issues = sm.validate_skill(skill_dir)
            status = "FAIL" if any(i.level == "error" for i in issues) else "ok"
            failed |= status == "FAIL"
            print(f"[{status}] {skill_dir.name}")
            for issue in issues:
                print(f"    {issue}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
