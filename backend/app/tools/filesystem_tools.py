"""Filesystem tools for reading and listing files.

Provides sandboxed file access within allowed directories,
with path traversal protection.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import structlog
from langchain_core.tools import tool

from app.config import settings

logger = structlog.get_logger(__name__)

# Allowed base directories for filesystem access
_ALLOWED_DIRS: list[Path] | None = None


def _get_allowed_dirs() -> list[Path]:
    """Get the list of directories the filesystem tools are allowed to access."""
    global _ALLOWED_DIRS
    if _ALLOWED_DIRS is None:
        _ALLOWED_DIRS = [
            settings.upload_path.resolve(),
            Path("./data").resolve(),
        ]
    return _ALLOWED_DIRS


def _validate_path(file_path: str) -> Path:
    """Validate that a file path is within allowed directories.

    Prevents path traversal attacks by resolving the absolute path
    and checking it's within an allowed directory.

    Args:
        file_path: The path to validate.

    Returns:
        Resolved Path object.

    Raises:
        PermissionError: If the path is outside allowed directories.
        FileNotFoundError: If the file does not exist.
    """
    resolved = Path(file_path).resolve()

    allowed = _get_allowed_dirs()
    is_allowed = any(str(resolved).startswith(str(d)) for d in allowed)

    if not is_allowed:
        raise PermissionError(
            f"Access denied: path is outside allowed directories. "
            f"Allowed: {[str(d) for d in allowed]}"
        )

    if not resolved.exists():
        raise FileNotFoundError(f"File not found: {resolved}")

    return resolved


@tool
async def filesystem_read_tool(file_path: str) -> str:
    """Read the contents of a text file.

    Only files within the application's data/uploads directories are accessible.
    Binary files are not supported.

    Args:
        file_path: Path to the file to read.

    Returns:
        The file contents as a string.
    """
    try:
        path = _validate_path(file_path)
    except (PermissionError, FileNotFoundError) as exc:
        return str(exc)

    if path.is_dir():
        return f"{file_path} is a directory, not a file. Use filesystem_list_tool instead."

    try:
        text = path.read_text(encoding="utf-8")
        # Cap for LLM context
        if len(text) > 20000:
            return text[:20000] + f"\n\n... [truncated, total {len(text)} characters]"
        return text
    except UnicodeDecodeError:
        return f"Cannot read {path.name}: file appears to be binary."
    except Exception as exc:
        return f"Error reading file: {exc}"


@tool
async def filesystem_list_tool(directory: str) -> str:
    """List files and subdirectories in a directory.

    Only directories within the application's data/uploads directories are accessible.

    Args:
        directory: Path to the directory to list.

    Returns:
        Formatted list of files with sizes and types.
    """
    try:
        path = _validate_path(directory)
    except PermissionError as exc:
        return str(exc)
    except FileNotFoundError:
        return f"Directory not found: {directory}"

    if not path.is_dir():
        return f"{directory} is not a directory."

    entries = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    if not entries:
        return f"Directory is empty: {directory}"

    lines = [f"Contents of {path}:"]
    for entry in entries[:100]:  # Cap listing
        if entry.is_dir():
            lines.append(f"  [DIR]  {entry.name}/")
        else:
            size_kb = entry.stat().st_size / 1024
            lines.append(f"  [FILE] {entry.name} ({size_kb:.1f} KB)")

    if len(entries) > 100:
        lines.append(f"  ... and {len(entries) - 100} more entries")

    return "\n".join(lines)


# All filesystem tools for agent binding
filesystem_tools = [filesystem_read_tool, filesystem_list_tool]
