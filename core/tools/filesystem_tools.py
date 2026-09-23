"""File, project, and upload-related tools."""

import os
import shutil
from datetime import datetime

from config import UPLOADS_DIR


def list_project_files(relative_path: str = ".") -> str:
    """List the files and folders inside the given path."""
    try:
        absolute_path = os.path.abspath(relative_path)
        if not os.path.exists(absolute_path):
            return f"Error: path '{relative_path}' does not exist."

        entries = os.listdir(absolute_path)
        if not entries:
            return f"Directory '{relative_path}' is empty."

        lines = [f"Files in '{relative_path}':"]
        for entry in sorted(entries):
            is_dir = os.path.isdir(os.path.join(absolute_path, entry))
            tag = "[DIR]" if is_dir else "[FILE]"
            lines.append(f"  {tag} {entry}")

        return "\n".join(lines)
    except Exception as e:
        return f"Error listing files: {e}"


def read_text_file(file_path: str, max_chars: int = 20000) -> str:
    """Read and return the contents of a text file (truncated if very large)."""
    try:
        if not os.path.exists(file_path):
            return f"Error: file '{file_path}' does not exist."

        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read(max_chars + 1)

        truncated = len(content) > max_chars
        content = content[:max_chars]
        suffix = "\n\n[... truncated ...]" if truncated else ""
        return f"--- Content of {file_path} ---\n{content}{suffix}"
    except Exception as e:
        return f"Error reading file: {e}"


def write_text_file(file_path: str, content: str) -> str:
    """Create or overwrite a text file with the given content."""
    try:
        os.makedirs(os.path.dirname(os.path.abspath(file_path)) or ".", exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"File '{file_path}' written successfully ({len(content)} characters)."
    except Exception as e:
        return f"Error writing file: {e}"


def import_uploaded_file(source_path: str) -> str:
    """
    Copy an external file (e.g. one the user attached from the UI) into the
    assistant's workspace/uploads folder, so it can be referenced by later
    tool calls (read_text_file, etc.) using a stable, sandboxed path.
    """
    try:
        if not os.path.exists(source_path):
            return f"Error: '{source_path}' does not exist."

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{timestamp}_{os.path.basename(source_path)}"
        destination = UPLOADS_DIR / filename
        shutil.copy2(source_path, destination)
        return f"File imported to workspace: {destination}"
    except Exception as e:
        return f"Error importing file: {e}"


def register(registry) -> None:
    registry.register(
        name="list_project_files",
        description="List files and folders inside a given directory.",
        parameters={
            "type": "object",
            "properties": {
                "relative_path": {"type": "string", "description": "Directory to list. Defaults to the current directory."},
            },
        },
        func=list_project_files,
    )
    registry.register(
        name="read_text_file",
        description="Read and return the contents of a text file.",
        parameters={
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Path of the file to read."},
                "max_chars": {"type": "integer", "description": "Maximum number of characters to return."},
            },
            "required": ["file_path"],
        },
        func=read_text_file,
    )
    registry.register(
        name="write_text_file",
        description="Create or overwrite a text file with the given content.",
        parameters={
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Path of the file to write."},
                "content": {"type": "string", "description": "Text content to write to the file."},
            },
            "required": ["file_path", "content"],
        },
        func=write_text_file,
    )
    registry.register(
        name="import_uploaded_file",
        description="Copy a file the user attached into the assistant's sandboxed workspace so it can be read by other tools.",
        parameters={
            "type": "object",
            "properties": {
                "source_path": {"type": "string", "description": "Path to the file the user attached."},
            },
            "required": ["source_path"],
        },
        func=import_uploaded_file,
    )
