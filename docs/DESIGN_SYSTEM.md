# Design system

`ui/theme.py` is the single source of truth for colour, spacing, radii, motion
and the global stylesheet. Widgets never ship their own palette: they opt into
shared styles with dynamic properties such as `secondary`, `danger` and
`muted`.

## Tokens

```python
SPACING = {"xs": 4, "sm": 8, "md": 12, "lg": 16}
RADII   = {"sm": 4, "md": 6, "lg": 8}
MOTION  = {"fast": 120, "normal": 240}
MIN_CONTROL_HEIGHT = 32
```

Colour tokens (`DARK` / `LIGHT`):

| Token | Role |
|---|---|
| `bg` | Window and chat background. |
| `surface` | Inputs, cards, menus, docks. |
| `text` / `muted` | Primary and secondary text. |
| `primary` / `on_primary` | Accent and text on accent. |
| `success` / `warning` / `error` | Semantic states and toasts. |
| `border` / `hover` | Dividers and hover surfaces. |
| `info` / `accent2` | Secondary accents (links, reasoning). |
| `log_text` | Dev Console monospace text. |

Typography uses `FONT_UI` (`Inter`, `Segoe UI`, system-ui) and `FONT_MONO`
(`JetBrains Mono`, `Fira Code`) for code, logs and completion rows.

## Themes

| Setting | Behaviour |
|---|---|
| `dark` | Default Tokyo-Night-inspired palette. |
| `light` | Light palette with the same semantic tokens. |
| `system` | Resolves through `QStyleHints.colorScheme()`; `watch_system_theme()` re-applies on OS changes. |

`apply_theme(app, setting)` sets `QApplication.setStyleSheet(build_stylesheet(...))`
and notifies listeners registered with `on_theme_changed()`. The MainWindow
rebuilds icons and the conversation on a theme change. Text/background pairs
are checked for WCAG AA contrast in `tests/test_theme_and_ux.py`.

## Component conventions

- Buttons use the default primary style, or `setProperty("secondary", True)`
  / `setProperty("danger", True)`.
- Muted labels use `setProperty("muted", True)`.
- Inputs, lists, menus, tabs, scrollbars, tooltips and docks are all styled from
  the one stylesheet; focus is a 2 px `primary` border.
- Controls are at least 32 px tall (`MIN_CONTROL_HEIGHT`), key widgets have
  `setAccessibleName`, and every action is keyboard-reachable.
- Icons are inline SVG strings in `ui/icons.py`, recoloured at runtime with
  `get_icon(name, color, size)`; there are no external image assets.

### Composer

The composer is a floating widget (`QWidget#composer`) over the conversation,
with a `bg` background and no border. It has two layouts:

| State | Layout | Height |
|---|---|---|
| Compact | `[attach] [field] [send]` on one row. | 52 px, grows with wrapped lines. |
| Expanded | Full-width field panel; attach bottom-left, send/cancel bottom-right. | Starts at 90 px, grows to 50 % of the window, then scrolls internally. |

`ChatInput` emits `expandedChanged(bool)` when the text gains a newline or no
longer fits the stored compact width. `heightChanged(int)` drives the chat's
bottom viewport margin, so growing the composer never squeezes the
conversation. The transition is debounced in the window and compares against
the compact width, not the current expanded width, to avoid flip-flopping.

### Other named styles

- `QListWidget#completionPopup` — monospace completion list.
- `QFrame#attachmentChip` — attachment chip surface.
- `QLabel#attachmentBadge` — numbered `#n` badge.

## Motion and feedback

Toasts (`ui/toast.py`) slide in and fade out using `MOTION`, and honour
`reduce_motion` by appearing without animation. Success, warning and error
toasts share the semantic tokens. Tool effects arrive as success toasts through
`DevLogger.event_logged`.

## Testing

`tests/test_theme_and_ux.py` covers contrast, theme resolution, composer layout
and growth limits, button sizing and accessibility names. Run the suite
headless with `QT_QPA_PLATFORM=offscreen`.
