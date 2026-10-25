"""Console execution, installed-application discovery/launch, and hardware status tools."""

import configparser
import glob
import os
import platform
import subprocess

from core import desktop_manager
from core import hardware_monitor

if platform.system().lower() == "windows":
    import winreg
else:
    winreg = None


def run_console_command(command: str, timeout_seconds: int = 30) -> str:
    """Run a shell command (Bash on Linux, CMD/PowerShell on Windows) and return its output."""
    if not command or not command.strip():
        return "Error: command must not be empty."

    if timeout_seconds <= 0:
        return "Error: timeout_seconds must be a positive integer."

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        stdout = result.stdout.strip()
        stderr = result.stderr.strip()

        parts = []
        if stdout:
            parts.append(f"**Output:**\n```\n{stdout}\n```")
        if stderr:
            parts.append(f"**Errors/warnings:**\n```\n{stderr}\n```")

        if result.returncode != 0:
            detail = "\n\n".join(parts) if parts else "(no output)"
            return (
                f"Error: command `{command}` exited with code {result.returncode}."
                f"\n\n{detail}"
            )
        if not parts:
            return f"Command `{command}` ran successfully (no text output)."
        return "\n\n".join(parts)

    except subprocess.TimeoutExpired:
        return f"Error: command `{command}` timed out after {timeout_seconds}s."
    except Exception as e:
        return f"Error: running command `{command}`: {type(e).__name__}: {e}"


def get_installed_applications() -> dict[str, str]:
    """Scan installed applications on the current OS. Returns {app_name: command_or_path}."""
    system = platform.system().lower()
    app_map: dict[str, str] = {}

    if "linux" in system:
        desktop_file_globs = [
            "/usr/share/applications/*.desktop",
            os.path.expanduser("~/.local/share/applications/*.desktop"),
        ]
        for pattern in desktop_file_globs:
            for desktop_file in glob.glob(pattern):
                parser = configparser.ConfigParser(interpolation=None)
                try:
                    parser.read(desktop_file, encoding="utf-8")
                    if "Desktop Entry" not in parser:
                        continue
                    entry = parser["Desktop Entry"]
                    if entry.get("NoDisplay") == "true":
                        continue
                    name = entry.get("Name")
                    exec_cmd = entry.get("Exec")
                    if name and exec_cmd:
                        clean_cmd = exec_cmd.split()[0].replace('"', "").replace("'", "")
                        app_map[name.lower()] = clean_cmd
                except Exception:
                    continue

    elif "windows" in system and winreg:
        registry_paths = [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"),
            (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"),
        ]
        for hive, subkey in registry_paths:
            try:
                with winreg.OpenKey(hive, subkey) as key:
                    subkey_count = winreg.QueryInfoKey(key)[0]
                    for i in range(subkey_count):
                        try:
                            exe_name = winreg.EnumKey(key, i)
                            app_name = os.path.splitext(exe_name)[0].lower()
                            with winreg.OpenKey(key, exe_name) as sub_key:
                                cmd_path, _ = winreg.QueryValueEx(sub_key, "")
                                app_map[app_name] = cmd_path
                        except Exception:
                            continue
            except Exception:
                continue

        start_menu_dirs = [
            os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs"),
            os.path.expandvars(r"%PROGRAMDATA%\Microsoft\Windows\Start Menu\Programs"),
        ]
        for folder in start_menu_dirs:
            for root, _, files in os.walk(folder):
                for file in files:
                    if file.endswith(".lnk"):
                        app_name = os.path.splitext(file)[0].lower()
                        app_map[app_name] = os.path.join(root, file)

    return app_map


def list_installed_applications() -> str:
    """AI-facing tool: return a readable list of installed applications."""
    apps = get_installed_applications()
    if not apps:
        return "Error: could not scan installed applications on this system."

    names = sorted(name.title() for name in apps.keys())[:35]
    return "Installed applications detected:\n" + "\n".join(f"- {n}" for n in names)


def open_application(app_name: str) -> str:
    """Launch an installed application, moving it to a secondary virtual desktop first."""
    if not app_name or not app_name.strip():
        return "Error: app_name must not be empty."

    apps = get_installed_applications()
    query = app_name.lower().strip()

    match = apps.get(query)
    if not match:
        for name, cmd in apps.items():
            if query in name:
                match = cmd
                break

    if not match:
        return f"Error: application '{app_name}' was not found among the installed applications."

    try:
        desktop_manager.move_to_secondary_desktop()
        if platform.system().lower() == "windows":
            subprocess.Popen(f'start "" "{match}"', shell=True)
        else:
            subprocess.Popen(match, shell=True)
        desktop_manager.return_to_main_desktop()
        return f"Launched '{app_name}' (`{match}`)."
    except Exception as e:
        desktop_manager.return_to_main_desktop()
        return f"Error: launching '{app_name}': {type(e).__name__}: {e}"


def get_hardware_status() -> str:
    """AI-facing tool: return a human-readable hardware status summary."""
    return hardware_monitor.format_snapshot_as_text()


def register(registry) -> None:
    registry.register(
        name="run_console_command",
        description=(
            "Execute a shell/terminal command (Bash on Linux, CMD/PowerShell on Windows) "
            "and return its stdout and stderr. Use this for running scripts, checking "
            "system state, file operations, package management, or any task that requires "
            "shell access. The command runs synchronously; long-running commands should "
            "set an appropriate timeout."
        ),
        parameters={
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The exact command to execute (e.g. 'ls -la', 'python script.py')."},
                "timeout_seconds": {"type": "integer", "description": "Maximum seconds to wait before killing the process. Default: 30."},
            },
            "required": ["command"],
        },
        func=run_console_command,
    )
    registry.register(
        name="list_installed_applications",
        description=(
            "Get a list of applications installed on the user's operating system. "
            "Use this to discover what apps are available before calling open_application."
        ),
        parameters={"type": "object", "properties": {}},
        func=list_installed_applications,
    )
    registry.register(
        name="open_application",
        description=(
            "Open an installed application by name (e.g. 'code', 'calc', 'firefox'). "
            "Use this to launch GUI applications the user asks to open. Handles Flatpak, "
            "Snap, and native binaries automatically."
        ),
        parameters={
            "type": "object",
            "properties": {
                "app_name": {"type": "string", "description": "Name or alias of the application to launch."},
            },
            "required": ["app_name"],
        },
        func=open_application,
    )
    registry.register(
        name="get_hardware_status",
        description=(
            "Get a live snapshot of the system's hardware usage: CPU utilization, RAM usage, "
            "network I/O, and GPU metrics (if available). Use this when diagnosing "
            "performance issues or checking system health."
        ),
        parameters={"type": "object", "properties": {}},
        func=get_hardware_status,
    )