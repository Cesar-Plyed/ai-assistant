# ui/commands.py
"""Slash commands shared by the chat input and the main window.

Keeping the catalogue in one place means the autocomplete popup and
``/help`` can never drift apart.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SlashCommand:
    name: str
    description: str


COMMANDS: tuple[SlashCommand, ...] = (
    SlashCommand("/clear", "Clear the chat history shown in this window"),
    SlashCommand("/help", "Show commands, mentions and tips"),
    SlashCommand("/dev", "Toggle the Dev Mode panel"),
    SlashCommand("/model", "Switch the active model"),
    SlashCommand("/settings", "Open Settings"),
    SlashCommand("/skills", "Manage skills"),
    SlashCommand("/mcp", "List MCP servers, tools and connection state"),
    SlashCommand("/new", "Start a new chat"),
    SlashCommand("/export", "Export this chat as Markdown"),
)


def command_pairs() -> list[tuple[str, str]]:
    """``(name, description)`` pairs for the completion popup."""
    return [(command.name, command.description) for command in COMMANDS]


def command_names() -> list[str]:
    return [command.name for command in COMMANDS]
