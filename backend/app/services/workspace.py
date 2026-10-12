"""Bounded, read-only file collection for software-engineer profile tasks."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

ALLOWED_SUFFIXES = {
    ".c",
    ".cfg",
    ".css",
    ".go",
    ".html",
    ".ini",
    ".java",
    ".js",
    ".json",
    ".jsx",
    ".md",
    ".py",
    ".rs",
    ".sh",
    ".sql",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".yaml",
    ".yml",
}
EXCLUDED_DIRS = {".git", ".next", ".venv", "__pycache__", "node_modules", "venv"}
EXCLUDED_NAMES = {".env", ".npmrc", "credentials", "id_rsa", "secrets"}
MAX_FILES = 40
MAX_FILE_CHARS = 8_000
MAX_TOTAL_CHARS = 120_000


class WorkspaceInputError(ValueError):
    """Requested workspace path is missing, outside the configured root, or unreadable."""


def read_workspace(root: Path, requested: str | None) -> tuple[str, list[str]]:
    """Read bounded text files under the configured root without following escapes."""
    root = root.expanduser().resolve()
    candidate = (root / requested).resolve() if requested else root
    if not candidate.is_relative_to(root):
        raise WorkspaceInputError("The selected path must stay inside the configured workspace.")
    if not candidate.exists() or not candidate.is_dir():
        raise WorkspaceInputError("The selected workspace path does not exist or is not a folder.")

    candidates = [candidate] if candidate.is_file() else candidate.rglob("*")
    files = sorted(
        path
        for path in candidates
        if path.is_file()
        and not any(
            part in EXCLUDED_DIRS or part.startswith(".")
            for part in path.relative_to(candidate).parts[:-1]
        )
        and path.name.lower() not in EXCLUDED_NAMES
        and path.suffix.lower() in ALLOWED_SUFFIXES
    )
    excerpts: list[str] = []
    sources: list[str] = []
    total = 0
    for path in files[:MAX_FILES]:
        resolved = path.resolve()
        if not resolved.is_relative_to(root) or path.name.lower() in EXCLUDED_NAMES:
            continue
        try:
            content = resolved.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        if "\x00" in content:
            continue
        excerpt = content[:MAX_FILE_CHARS]
        if total + len(excerpt) > MAX_TOTAL_CHARS:
            excerpt = excerpt[: MAX_TOTAL_CHARS - total]
        if not excerpt:
            break
        relative = resolved.relative_to(root).as_posix()
        sources.append(relative)
        excerpts.append(f"--- {relative} ---\n{excerpt}")
        total += len(excerpt)
        if total >= MAX_TOTAL_CHARS:
            break
    if not excerpts:
        raise WorkspaceInputError("No supported readable source files were found in that path.")
    return "\n\n".join(excerpts), sources
