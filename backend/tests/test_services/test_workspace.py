from pathlib import Path

import pytest

from app.services.workspace import WorkspaceInputError, read_workspace


def test_workspace_reader_selects_supported_files_and_skips_secrets(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "module.py").write_text("print('safe')", encoding="utf-8")
    (root / ".env").write_text("TOKEN=private", encoding="utf-8")
    (root / "image.png").write_bytes(b"not read")
    (root / "node_modules").mkdir()
    (root / "node_modules" / "dep.py").write_text("ignored", encoding="utf-8")

    content, sources = read_workspace(root, ".")

    assert "print('safe')" in content
    assert "private" not in content
    assert "ignored" not in content
    assert sources == ["module.py"]


def test_workspace_reader_rejects_paths_outside_configured_root(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    outside = tmp_path / "secret.py"
    outside.write_text("private", encoding="utf-8")

    with pytest.raises(WorkspaceInputError, match="inside the configured workspace"):
        read_workspace(root, "../secret.py")


def test_workspace_reader_rejects_symlink_escape(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("private", encoding="utf-8")
    (root / "escape.py").symlink_to(outside)

    with pytest.raises(WorkspaceInputError, match="No supported readable"):
        read_workspace(root, ".")
