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
    if not config.SETTINGS.get("enable_mouse_control", False):
        return (
            "BLOCKED: mouse/keyboard control is disabled. The user can enable it in "
            "Settings > 'Enable mouse/keyboard control' if they want the "
            "assistant to be able to move the mouse, click, or type directly."
        )
    return None


def take_screenshot(save_path: str = "workspace/screenshot.png") -> str:
    """Capture the full screen and save it as a PNG image."""
    denied = _guard()
    if denied:
        return denied
    if not save_path or not save_path.strip():
        return "Error: save_path must not be empty."
    try:
        import pyautogui
        image = pyautogui.screenshot()
        image.save(save_path)
        return f"Screenshot saved to {save_path}."
    except Exception as e:
        return f"Error: taking screenshot: {type(e).__name__}: {e}"


def move_mouse(x: int, y: int, duration_seconds: float = 0.3) -> str:
    """Move the mouse cursor to an absolute screen position."""
    denied = _guard()
    if denied:
        return denied
    if duration_seconds < 0:
        return "Error: duration_seconds must be non-negative."
    try:
        import pyautogui
        # pyautogui.size() reports the primary monitor only; on multi-monitor
        # setups coordinates can be negative or exceed primary bounds, so we
        # only sanity-check that the values are non-negative integers.
        if not (isinstance(x, int) and isinstance(y, int) and x >= 0 and y >= 0):
            return f"Error: coordinates ({x}, {y}) must be non-negative integers."
        pyautogui.moveTo(x, y, duration=duration_seconds)
        return f"Mouse moved to ({x}, {y})."
    except Exception as e:
        return f"Error: moving mouse: {type(e).__name__}: {e}"


def click_mouse(x: int | None = None, y: int | None = None, button: str = "left") -> str:
    """Click the mouse at the given position (or current position if omitted)."""
    denied = _guard()
    if denied:
        return denied
    if x is not None and y is not None:
        try:
            import pyautogui
            # pyautogui.size() reports the primary monitor only; on multi-monitor
            # setups coordinates can be negative or exceed primary bounds, so we
            # only sanity-check that the values are non-negative integers.
            if not (isinstance(x, int) and isinstance(y, int) and x >= 0 and y >= 0):
                return f"Error: coordinates ({x}, {y}) must be non-negative integers."
            pyautogui.click(x=x, y=y, button=button)
            return f"Clicked ({button}) at ({x}, {y})."
        except Exception as e:
            return f"Error: clicking at ({x}, {y}): {type(e).__name__}: {e}"
    try:
        import pyautogui
        pyautogui.click(button=button)
        return f"Clicked ({button}) at the current mouse position."
    except Exception as e:
        return f"Error: clicking: {type(e).__name__}: {e}"


def type_text(text: str, interval_seconds: float = 0.02) -> str:
    """Type text at the current keyboard focus."""
    denied = _guard()
    if denied:
        return denied
    if not text:
        return "Error: text must not be empty."
    if interval_seconds < 0:
        return "Error: interval_seconds must be non-negative."
    try:
        import pyautogui
        pyautogui.typewrite(text, interval=interval_seconds)
        return f"Typed {len(text)} characters."
    except Exception as e:
        return f"Error: typing text: {type(e).__name__}: {e}"


def press_key(key_name: str) -> str:
    """Press a single keyboard key (e.g. 'enter', 'esc', 'tab')."""
    denied = _guard()
    if denied:
        return denied
    if not key_name or not key_name.strip():
        return "Error: key_name must not be empty."
    try:
        import pyautogui
        pyautogui.press(key_name.strip())
        return f"Pressed key '{key_name}'."
    except Exception as e:
        return f"Error: pressing key '{key_name}': {type(e).__name__}: {e}"


def register(registry) -> None:
    registry.register(
        name="take_screenshot",
        description=(
            "Take a screenshot of the entire screen and save it to a file. "
            "Use this to see what is currently on screen, verify visual state, "
            "or debug UI issues. Requires mouse/keyboard control to be enabled."
        ),
        parameters={
            "type": "object",
            "properties": {"save_path": {"type": "string", "description": "File path to save the screenshot (PNG). Default: workspace/screenshot.png."}},
        },
        func=take_screenshot,
    )
    registry.register(
        name="move_mouse",
        description=(
            "Move the mouse cursor to an absolute screen position (x, y). "
            "Use this to reposition the cursor before a click or to bring attention "
            "to a specific UI element. Coordinates are in pixels from the top-left corner."
        ),
        parameters={
            "type": "object",
            "properties": {
                "x": {"type": "integer", "description": "Horizontal position in pixels (0 = left edge)."},
                "y": {"type": "integer", "description": "Vertical position in pixels (0 = top edge)."},
                "duration_seconds": {"type": "number", "description": "Time in seconds for the movement animation. Default: 0.3."},
            },
            "required": ["x", "y"],
        },
        func=move_mouse,
    )
    registry.register(
        name="click_mouse",
        description=(
            "Click the mouse at a given position or at the current cursor position. "
            "Use this to click buttons, links, menu items, or any clickable UI element. "
            "Specify both x and y to click at a specific location, or omit them to click "
            "where the cursor already is."
        ),
        parameters={
            "type": "object",
            "properties": {
                "x": {"type": "integer", "description": "Horizontal position in pixels. Omit to click at the current position."},
                "y": {"type": "integer", "description": "Vertical position in pixels. Omit to click at the current position."},
                "button": {"type": "string", "enum": ["left", "right", "middle"], "description": "Mouse button to click. Default: left."},
            },
        },
        func=click_mouse,
    )
    registry.register(
        name="type_text",
        description=(
            "Type text at the current keyboard focus. Use this to fill in text fields, "
            "enter search queries, or input commands. The text appears wherever the "
            "user's cursor is currently focused."
        ),
        parameters={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "The text to type."},
                "interval_seconds": {"type": "number", "description": "Delay between keystrokes in seconds. Default: 0.02."},
            },
            "required": ["text"],
        },
        func=type_text,
    )
    registry.register(
        name="press_key",
        description=(
            "Press a single keyboard key. Use this to submit forms (Enter), navigate "
            "(Tab), cancel (Escape), or trigger keyboard shortcuts. The key is sent to "
            "the currently focused element."
        ),
        parameters={
            "type": "object",
            "properties": {"key_name": {"type": "string", "description": "Key name (e.g. 'enter', 'esc', 'tab', 'ctrl+s')."}},
            "required": ["key_name"],
        },
        func=press_key,
    )