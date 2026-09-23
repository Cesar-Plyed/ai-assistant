"""
Optional mouse/keyboard automation tools, built on PyAutoGUI.

These give the assistant literal control of the mouse and keyboard, which is
powerful but risky (a mistaken click can do real damage). They are disabled
by default; the user must explicitly turn on "Enable mouse/keyboard control"
in Settings before these tools will do anything. Every call re-checks the
flag, so toggling it off in the UI takes effect immediately, even mid-task.
"""

import config


def _guard() -> str | None:
    # Read config.SETTINGS through the module (not a local copy imported at
    # load time) so a live toggle in Settings is picked up immediately,
    # even mid-session.
    if not config.SETTINGS.get("enable_mouse_control", False):
        return (
            "Mouse/keyboard control is disabled. The user can enable it in "
            "Settings > 'Enable mouse/keyboard control' if they want the "
            "assistant to be able to move the mouse, click, or type directly."
        )
    return None


def take_screenshot(save_path: str = "workspace/screenshot.png") -> str:
    denied = _guard()
    if denied:
        return denied
    try:
        import pyautogui
        image = pyautogui.screenshot()
        image.save(save_path)
        return f"Screenshot saved to {save_path}."
    except Exception as e:
        return f"Error taking screenshot: {e}"


def move_mouse(x: int, y: int, duration_seconds: float = 0.3) -> str:
    denied = _guard()
    if denied:
        return denied
    try:
        import pyautogui
        pyautogui.moveTo(x, y, duration=duration_seconds)
        return f"Mouse moved to ({x}, {y})."
    except Exception as e:
        return f"Error moving mouse: {e}"


def click_mouse(x: int | None = None, y: int | None = None, button: str = "left") -> str:
    denied = _guard()
    if denied:
        return denied
    try:
        import pyautogui
        if x is not None and y is not None:
            pyautogui.click(x=x, y=y, button=button)
            return f"Clicked ({button}) at ({x}, {y})."
        pyautogui.click(button=button)
        return f"Clicked ({button}) at the current mouse position."
    except Exception as e:
        return f"Error clicking: {e}"


def type_text(text: str, interval_seconds: float = 0.02) -> str:
    denied = _guard()
    if denied:
        return denied
    try:
        import pyautogui
        pyautogui.typewrite(text, interval=interval_seconds)
        return f"Typed {len(text)} characters."
    except Exception as e:
        return f"Error typing text: {e}"


def press_key(key_name: str) -> str:
    denied = _guard()
    if denied:
        return denied
    try:
        import pyautogui
        pyautogui.press(key_name)
        return f"Pressed key '{key_name}'."
    except Exception as e:
        return f"Error pressing key: {e}"


def register(registry) -> None:
    registry.register(
        name="take_screenshot",
        description="Take a screenshot of the screen and save it to a file. Requires mouse/keyboard control to be enabled in Settings.",
        parameters={
            "type": "object",
            "properties": {"save_path": {"type": "string", "description": "Where to save the screenshot."}},
        },
        func=take_screenshot,
    )
    registry.register(
        name="move_mouse",
        description="Move the mouse cursor to a screen position. Requires mouse/keyboard control to be enabled in Settings.",
        parameters={
            "type": "object",
            "properties": {
                "x": {"type": "integer"},
                "y": {"type": "integer"},
                "duration_seconds": {"type": "number"},
            },
            "required": ["x", "y"],
        },
        func=move_mouse,
    )
    registry.register(
        name="click_mouse",
        description="Click the mouse, optionally at a given position. Requires mouse/keyboard control to be enabled in Settings.",
        parameters={
            "type": "object",
            "properties": {
                "x": {"type": "integer"},
                "y": {"type": "integer"},
                "button": {"type": "string", "enum": ["left", "right", "middle"]},
            },
        },
        func=click_mouse,
    )
    registry.register(
        name="type_text",
        description="Type text using the keyboard at the current focus. Requires mouse/keyboard control to be enabled in Settings.",
        parameters={
            "type": "object",
            "properties": {"text": {"type": "string"}, "interval_seconds": {"type": "number"}},
            "required": ["text"],
        },
        func=type_text,
    )
    registry.register(
        name="press_key",
        description="Press a single keyboard key (e.g. 'enter', 'esc', 'tab'). Requires mouse/keyboard control to be enabled in Settings.",
        parameters={
            "type": "object",
            "properties": {"key_name": {"type": "string"}},
            "required": ["key_name"],
        },
        func=press_key,
    )
