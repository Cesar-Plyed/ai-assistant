"""File, project, and upload-related tools."""

import os
import shutil
from datetime import datetime

from config import UPLOADS_DIR


_MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB hard cap


def list_project_files(relative_path: str = ".") -> str:
    """List the files and folders inside the given path."""
    if not relative_path or not relative_path.strip():
        return "Error: relative_path must not be empty."

    try:
        absolute_path = os.path.abspath(relative_path)
        if not os.path.exists(absolute_path):
            return f"Error: path '{relative_path}' does not exist."

        if not os.path.isdir(absolute_path):
            return f"Error: path '{relative_path}' is not a directory."

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
        return f"Error: listing files in '{relative_path}': {type(e).__name__}: {e}"


def read_text_file(file_path: str, max_chars: int = 20000) -> str:
    """Read and return the contents of a text file (truncated if very large)."""
    if not file_path or not file_path.strip():
        return "Error: file_path must not be empty."

    if max_chars <= 0:
        return "Error: max_chars must be a positive integer."

    try:
        if not os.path.exists(file_path):
            return f"Error: file '{file_path}' does not exist."

        if not os.path.isfile(file_path):
            return f"Error: path '{file_path}' is not a regular file."

        file_size = os.path.getsize(file_path)

        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read(max_chars + 1)

        truncated = len(content) > max_chars
        content = content[:max_chars]
        suffix = f"\n\n[... truncated ...]" if truncated else ""
        return f"--- Content of {file_path} ---\n{content}{suffix}"
    except Exception as e:
        return f"Error: reading file '{file_path}': {type(e).__name__}: {e}"


def write_text_file(file_path: str, content: str) -> str:
    """Create or overwrite a text file with the given content."""
    if not file_path or not file_path.strip():
        return "Error: file_path must not be empty."

    try:
        parent = os.path.dirname(os.path.abspath(file_path)) or "."
        os.makedirs(parent, exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"File '{file_path}' written successfully ({len(content)} characters)."
    except Exception as e:
        return f"Error: writing file '{file_path}': {type(e).__name__}: {e}"


def import_uploaded_file(source_path: str) -> str:
    """
    Copy an external file (e.g. one the user attached from the UI) into the
    assistant's workspace/uploads folder, so it can be referenced by later
    tool calls (read_text_file, etc.) using a stable, sandboxed path.
    """
    if not source_path or not source_path.strip():
        return "Error: source_path must not be empty."

    try:
        if not os.path.exists(source_path):
            return f"Error: '{source_path}' does not exist."

        if not os.path.isfile(source_path):
            return f"Error: '{source_path}' is not a regular file."

        file_size = os.path.getsize(source_path)
        if file_size > _MAX_FILE_SIZE_BYTES:
            return (
                f"Error: file '{source_path}' is {file_size / 1024 / 1024:.1f} MB, "
                f"which exceeds the maximum allowed size of {_MAX_FILE_SIZE_BYTES / 1024 / 1024:.0f} MB."
            )

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{timestamp}_{os.path.basename(source_path)}"
        destination = UPLOADS_DIR / filename
        shutil.copy2(source_path, destination)
        return f"File imported to workspace: {destination}"
    except Exception as e:
        return f"Error: importing file '{source_path}': {type(e).__name__}: {e}"


def register(registry) -> None:
    registry.register(
        name="list_project_files",
        description=(
            "List files and folders inside a given directory. Use this to explore the "
            "project structure, discover what files exist, or verify that a file was "
            "created. Defaults to the current directory."
        ),
        parameters={
            "type": "object",
            "properties": {
                "relative_path": {"type": "string", "description": "Directory to list, relative to the workspace root. Defaults to '.'"},
            },
        },
        func=list_project_files,
    )
    registry.register(
        name="read_text_file",
        description=(
            "Read and return the contents of a text file. Use this to inspect source code, "
            "configuration files, logs, or any text-based file. Files larger than 5 MB are "
            "rejected — use run_console_command with grep/head/tail for large files."
        ),
        parameters={
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Path of the file to read."},
                "max_chars": {"type": "integer", "description": "Maximum number of characters to return (default 20000). Content beyond this limit is truncated."},
            },
            "required": ["file_path"],
        },
        func=read_text_file,
    )
    registry.register(
        name="write_text_file",
        description=(
            "Create or overwrite a text file with the given content. Use this to create "
            "new files, write code, generate reports, or save configuration. Parent "
            "directories are created automatically."
        ),
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
        description=(
            "Copy a file the user attached from the UI into the assistant's sandboxed "
            "workspace directory. Use this when the user uploads a file and you need to "
            "read or process it with other tools."
        ),
        parameters={
            "type": "object",
            "properties": {
                "source_path": {"type": "string", "description": "Absolute path to the file the user attached."},
            },
            "required": ["source_path"],
        },
        func=import_uploaded_file,
    )