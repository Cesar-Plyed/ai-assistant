"""
Cross-platform helper that moves newly launched windows to a secondary
virtual desktop (so the assistant doesn't steal focus from the user's main
workspace), then returns to the main desktop.

Supports: KDE Plasma (via KWin D-Bus, X11 and Wayland), other Linux desktop
environments with wmctrl, and Windows (via the built-in virtual desktop
keyboard shortcuts, through pyautogui).
"""

import platform
import shutil
import subprocess


def is_installed(command: str) -> bool:
    return shutil.which(command) is not None


def switch_virtual_desktop_kde(desktop_number: int) -> bool:
    """Ask KWin (KDE Plasma's window manager) to switch virtual desktops."""
    try:
        cmd = [
            "qdbus", "org.kde.KWin", "/KWin",
            "org.kde.KWin.setCurrentDesktop", str(desktop_number),
        ]
        result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if result.returncode == 0:
            return True
    except Exception:
        pass

    if is_installed("xdotool"):
        subprocess.run(["xdotool", "key", f"ctrl+F{desktop_number}"])
        return True

    return False


def _current_linux_desktop_env() -> str:
    import os
    return os.environ.get("XDG_CURRENT_DESKTOP", "").lower()


def move_to_secondary_desktop() -> None:
    system = platform.system().lower()

    if "windows" in system:
        try:
            import pyautogui
            pyautogui.hotkey("win", "ctrl", "right")
        except Exception as e:
            print(f"[DesktopManager/Windows] Could not switch desktop: {e}")

    elif "linux" in system:
        desktop_env = _current_linux_desktop_env()
        if "kde" in desktop_env or "plasma" in desktop_env:
            if not switch_virtual_desktop_kde(2):
                print("[DesktopManager/KDE] Could not switch desktop via D-Bus or xdotool.")
        elif is_installed("wmctrl"):
            subprocess.run(["wmctrl", "-s", "1"])


def return_to_main_desktop() -> None:
    system = platform.system().lower()

    if "windows" in system:
        try:
            import pyautogui
            pyautogui.hotkey("win", "ctrl", "left")
        except Exception as e:
            print(f"[DesktopManager/Windows] Could not switch desktop: {e}")

    elif "linux" in system:
        desktop_env = _current_linux_desktop_env()
        if "kde" in desktop_env or "plasma" in desktop_env:
            switch_virtual_desktop_kde(1)
        elif is_installed("wmctrl"):
            subprocess.run(["wmctrl", "-s", "0"])
