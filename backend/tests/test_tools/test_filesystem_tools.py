"""Tests for filesystem_tools — security-critical path validation + file ops.

Focuses on:
  - Path traversal prevention (_validate_path)
  - filesystem_read_tool (text, binary, truncation, dir guard)
  - filesystem_list_tool (listing, empty, cap, not-a-dir)
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest


# =============================================================================
# _validate_path — path traversal protection
# =============================================================================


class TestValidatePath:
    """Tests for the internal _validate_path function."""

    def _get_validate_path(self):
        """Import with fresh allowed-dirs cache."""
        from app.tools import filesystem_tools

        # Reset the cached allowed dirs so tests can control them
        filesystem_tools._ALLOWED_DIRS = None
        return filesystem_tools._validate_path

    def test_allows_path_inside_upload_dir(self, tmp_path: Path) -> None:
        test_file = tmp_path / "data.txt"
        test_file.write_text("content")

        with patch("app.tools.filesystem_tools._get_allowed_dirs", return_value=[tmp_path]):
            from app.tools.filesystem_tools import _validate_path

            result = _validate_path(str(test_file))
            assert result == test_file.resolve()

    def test_rejects_path_outside_allowed_dirs(self, tmp_path: Path) -> None:
        outside = tmp_path / "outside.txt"
        outside.write_text("secret")
        allowed = tmp_path / "allowed"
        allowed.mkdir()

        with patch("app.tools.filesystem_tools._get_allowed_dirs", return_value=[allowed]):
            from app.tools.filesystem_tools import _validate_path

            with pytest.raises(PermissionError, match="Access denied"):
                _validate_path(str(outside))

    def test_rejects_path_traversal_with_dotdot(self, tmp_path: Path) -> None:
        allowed = tmp_path / "allowed"
        allowed.mkdir()
        secret = tmp_path / "secret.txt"
        secret.write_text("secrets")

        traversal_path = str(allowed / ".." / "secret.txt")

        with patch("app.tools.filesystem_tools._get_allowed_dirs", return_value=[allowed]):
            from app.tools.filesystem_tools import _validate_path

            with pytest.raises(PermissionError, match="Access denied"):
                _validate_path(traversal_path)

    def test_rejects_nonexistent_file(self, tmp_path: Path) -> None:
        with patch("app.tools.filesystem_tools._get_allowed_dirs", return_value=[tmp_path]):
            from app.tools.filesystem_tools import _validate_path

            with pytest.raises(FileNotFoundError, match="File not found"):
                _validate_path(str(tmp_path / "no_such_file.txt"))

    def test_allows_path_in_data_dir(self, tmp_path: Path) -> None:
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        test_file = data_dir / "file.txt"
        test_file.write_text("ok")

        with patch("app.tools.filesystem_tools._get_allowed_dirs", return_value=[data_dir]):
            from app.tools.filesystem_tools import _validate_path

            result = _validate_path(str(test_file))
            assert result == test_file.resolve()

    def test_rejects_symlink_pointing_outside(self, tmp_path: Path) -> None:
        allowed = tmp_path / "allowed"
        allowed.mkdir()
        outside = tmp_path / "outside.txt"
        outside.write_text("nope")
        symlink = allowed / "sneaky.txt"
        symlink.symlink_to(outside)

        with patch("app.tools.filesystem_tools._get_allowed_dirs", return_value=[allowed]):
            from app.tools.filesystem_tools import _validate_path

            with pytest.raises(PermissionError, match="Access denied"):
                _validate_path(str(symlink))


# =============================================================================
# filesystem_read_tool
# =============================================================================


class TestFilesystemReadTool:
    """Tests for the filesystem_read_tool LangChain tool."""

    async def test_read_text_file(self, tmp_path: Path) -> None:
        test_file = tmp_path / "hello.txt"
        test_file.write_text("Hello, world!")

        with patch("app.tools.filesystem_tools._get_allowed_dirs", return_value=[tmp_path]):
            from app.tools.filesystem_tools import filesystem_read_tool

            result = await filesystem_read_tool.ainvoke({"file_path": str(test_file)})
            assert result == "Hello, world!"

    async def test_read_truncates_large_file(self, tmp_path: Path) -> None:
        test_file = tmp_path / "big.txt"
        content = "x" * 25000
        test_file.write_text(content)

        with patch("app.tools.filesystem_tools._get_allowed_dirs", return_value=[tmp_path]):
            from app.tools.filesystem_tools import filesystem_read_tool

            result = await filesystem_read_tool.ainvoke({"file_path": str(test_file)})
            assert "truncated" in result
            assert "25000 characters" in result
            assert len(result) < 25000

    async def test_read_binary_file(self, tmp_path: Path) -> None:
        test_file = tmp_path / "binary.bin"
        test_file.write_bytes(b"\x00\x01\x02\xff\xfe")

        with patch("app.tools.filesystem_tools._get_allowed_dirs", return_value=[tmp_path]):
            from app.tools.filesystem_tools import filesystem_read_tool

            result = await filesystem_read_tool.ainvoke({"file_path": str(test_file)})
            assert "binary" in result.lower()

    async def test_read_directory_returns_hint(self, tmp_path: Path) -> None:
        with patch("app.tools.filesystem_tools._get_allowed_dirs", return_value=[tmp_path]):
            from app.tools.filesystem_tools import filesystem_read_tool

            result = await filesystem_read_tool.ainvoke({"file_path": str(tmp_path)})
            assert "directory" in result.lower()
            assert "filesystem_list_tool" in result

    async def test_read_permission_denied(self, tmp_path: Path) -> None:
        allowed = tmp_path / "allowed"
        allowed.mkdir()

        with patch("app.tools.filesystem_tools._get_allowed_dirs", return_value=[allowed]):
            from app.tools.filesystem_tools import filesystem_read_tool

            result = await filesystem_read_tool.ainvoke({"file_path": "/etc/passwd"})
            assert "Access denied" in result

    async def test_read_nonexistent_file(self, tmp_path: Path) -> None:
        with patch("app.tools.filesystem_tools._get_allowed_dirs", return_value=[tmp_path]):
            from app.tools.filesystem_tools import filesystem_read_tool

            result = await filesystem_read_tool.ainvoke({"file_path": str(tmp_path / "nope.txt")})
            assert "not found" in result.lower() or "File not found" in result


# =============================================================================
# filesystem_list_tool
# =============================================================================


class TestFilesystemListTool:
    """Tests for the filesystem_list_tool LangChain tool."""

    async def test_list_directory(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("a")
        (tmp_path / "b.txt").write_text("b")
        (tmp_path / "subdir").mkdir()

        with patch("app.tools.filesystem_tools._get_allowed_dirs", return_value=[tmp_path]):
            from app.tools.filesystem_tools import filesystem_list_tool

            result = await filesystem_list_tool.ainvoke({"directory": str(tmp_path)})
            assert "[DIR]" in result
            assert "subdir/" in result
            assert "a.txt" in result
            assert "b.txt" in result

    async def test_list_empty_directory(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty"
        empty.mkdir()

        with patch("app.tools.filesystem_tools._get_allowed_dirs", return_value=[tmp_path]):
            from app.tools.filesystem_tools import filesystem_list_tool

            result = await filesystem_list_tool.ainvoke({"directory": str(empty)})
            assert "empty" in result.lower()

    async def test_list_not_a_directory(self, tmp_path: Path) -> None:
        f = tmp_path / "file.txt"
        f.write_text("hi")

        with patch("app.tools.filesystem_tools._get_allowed_dirs", return_value=[tmp_path]):
            from app.tools.filesystem_tools import filesystem_list_tool

            result = await filesystem_list_tool.ainvoke({"directory": str(f)})
            assert "not a directory" in result.lower()

    async def test_list_permission_denied(self, tmp_path: Path) -> None:
        allowed = tmp_path / "allowed"
        allowed.mkdir()

        with patch("app.tools.filesystem_tools._get_allowed_dirs", return_value=[allowed]):
            from app.tools.filesystem_tools import filesystem_list_tool

            result = await filesystem_list_tool.ainvoke({"directory": "/etc"})
            assert "Access denied" in result

    async def test_list_nonexistent_directory(self, tmp_path: Path) -> None:
        with patch("app.tools.filesystem_tools._get_allowed_dirs", return_value=[tmp_path]):
            from app.tools.filesystem_tools import filesystem_list_tool

            result = await filesystem_list_tool.ainvoke({"directory": str(tmp_path / "nope")})
            assert "not found" in result.lower()

    async def test_list_shows_file_sizes(self, tmp_path: Path) -> None:
        f = tmp_path / "sized.txt"
        f.write_text("x" * 2048)

        with patch("app.tools.filesystem_tools._get_allowed_dirs", return_value=[tmp_path]):
            from app.tools.filesystem_tools import filesystem_list_tool

            result = await filesystem_list_tool.ainvoke({"directory": str(tmp_path)})
            assert "KB" in result

    async def test_list_caps_at_100_entries(self, tmp_path: Path) -> None:
        for i in range(110):
            (tmp_path / f"file_{i:03d}.txt").write_text(str(i))

        with patch("app.tools.filesystem_tools._get_allowed_dirs", return_value=[tmp_path]):
            from app.tools.filesystem_tools import filesystem_list_tool

            result = await filesystem_list_tool.ainvoke({"directory": str(tmp_path)})
            assert "10 more entries" in result


# =============================================================================
# Tools list export
# =============================================================================


class TestToolsExport:
    def test_filesystem_tools_list(self) -> None:
        from app.tools.filesystem_tools import filesystem_tools

        assert len(filesystem_tools) == 2
        names = {t.name for t in filesystem_tools}
        assert "filesystem_read_tool" in names
        assert "filesystem_list_tool" in names
