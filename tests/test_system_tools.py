"""Console tool failure reporting, without relying on POSIX-only commands."""

import sys

from core.tools.system_tools import run_console_command


def test_nonzero_exit_code_is_reported_as_an_error():
    result = run_console_command(f'"{sys.executable}" -c "import sys; sys.exit(3)"')

    assert result.startswith("Error:")
    assert "exited with code 3" in result


def test_successful_command_keeps_its_output():
    result = run_console_command(f'"{sys.executable}" -c "print(42)"')

    assert "42" in result
    assert not result.startswith("Error:")
