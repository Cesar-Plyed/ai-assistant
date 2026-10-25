import subprocess
import sys


def test_ai_assistant_home_isolates_data(tmp_path):
    code = (
        "import config; from core import memory; "
        "print(config.BASE_DIR); print(memory.CHATS_DIR); print(config.SKILLS_DIR)"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True,
        env={**__import__("os").environ, "AI_ASSISTANT_HOME": str(tmp_path)},
    ).stdout.split()
    assert out[0] == str(tmp_path.resolve())
    assert out[1].startswith(str(tmp_path.resolve()))
    assert (tmp_path / "skills" / "example-skill" / "SKILL.md").exists()
