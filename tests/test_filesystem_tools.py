from __future__ import annotations

import asyncio

import pytest

import app.services.tools.base as base_mod
from app.services.tools.filesystem import (
    FILESYSTEM_TOOLS,
    FileSystemList,
    FileSystemRead,
    FileSystemWrite,
)


@pytest.fixture
def set_workspace(tmp_path, monkeypatch):
    """Pin the approved workspace to a temp directory."""
    monkeypatch.setattr(base_mod.config, "workspace_paths", [str(tmp_path)])
    return tmp_path


def run_async(coroutine):
    return asyncio.run(coroutine)


# ---------------------------------------------------------------------------
# filesystem.list
# ---------------------------------------------------------------------------

def test_list_lists_entries(set_workspace):
    (set_workspace / "a.txt").write_text("hello", encoding="utf-8")
    (set_workspace / "sub").mkdir()

    result = run_async(FileSystemList().execute({"path": str(set_workspace)}))
    assert result.success is True
    assert result.metadata["count"] == 2
    names = {e["name"]: e for e in result.output}
    assert names["a.txt"]["type"] == "file"
    assert names["a.txt"]["size"] == 5
    assert names["sub"]["type"] == "directory"
    assert names["sub"]["size"] == 0


def test_list_subdirectory(set_workspace):
    (set_workspace / "sub").mkdir()
    (set_workspace / "sub" / "inner.txt").write_text("x", encoding="utf-8")

    result = run_async(FileSystemList().execute({"path": str(set_workspace / "sub")}))
    assert result.success is True
    assert result.metadata["count"] == 1


def test_list_outside_workspace_rejected(set_workspace, tmp_path):
    outside = tmp_path.parent / "unrelated_ws"
    outside.mkdir(exist_ok=True)
    result = run_async(FileSystemList().execute({"path": str(outside)}))
    assert result.success is False
    assert "outside approved workspace" in result.error


def test_list_nonexistent_path(set_workspace):
    result = run_async(FileSystemList().execute({"path": str(set_workspace / "ghost")}))
    assert result.success is False
    assert "does not exist" in result.error


def test_list_non_directory(set_workspace):
    (set_workspace / "f.txt").write_text("x", encoding="utf-8")
    result = run_async(FileSystemList().execute({"path": str(set_workspace / "f.txt")}))
    assert result.success is False
    assert "not a directory" in result.error


def test_list_validate_input():
    tool = FileSystemList()
    with pytest.raises(ValueError):
        tool.validate_input({})
    with pytest.raises(ValueError):
        tool.validate_input({"path": 42})


# ---------------------------------------------------------------------------
# filesystem.read
# ---------------------------------------------------------------------------

def test_read_file(set_workspace):
    target = set_workspace / "note.txt"
    target.write_text("sunday\ncontent", encoding="utf-8")

    result = run_async(FileSystemRead().execute({"path": str(target)}))
    assert result.success is True
    assert result.output["content"] == "sunday\ncontent"
    assert result.output["size"] == len("sunday\ncontent".encode("utf-8"))
    assert result.output["lines"] == 2
    assert result.metadata["path"].endswith("note.txt")


def test_read_outside_workspace_rejected(set_workspace, tmp_path):
    outside = tmp_path.parent / "unrelated_ws"
    outside.mkdir(exist_ok=True)
    result = run_async(FileSystemRead().execute({"path": str(outside / "x.txt")}))
    assert result.success is False
    assert "outside approved workspace" in result.error


def test_read_missing_file(set_workspace):
    result = run_async(FileSystemRead().execute({"path": str(set_workspace / "nope.txt")}))
    assert result.success is False
    assert "not found" in result.error.lower()


def test_read_directory_returns_error(set_workspace):
    (set_workspace / "sub").mkdir()
    result = run_async(FileSystemRead().execute({"path": str(set_workspace / "sub")}))
    assert result.success is False
    assert "not a file" in result.error.lower()


def test_read_validate_input():
    tool = FileSystemRead()
    with pytest.raises(ValueError):
        tool.validate_input({})
    with pytest.raises(ValueError):
        tool.validate_input({"path": None})


# ---------------------------------------------------------------------------
# filesystem.write
# ---------------------------------------------------------------------------

def test_write_creates_new_file(set_workspace):
    target = set_workspace / "out.txt"
    result = run_async(FileSystemWrite().execute({"path": str(target), "content": "new data"}))

    assert result.success is True
    assert target.read_text(encoding="utf-8") == "new data"
    assert result.output["size"] == len("new data".encode("utf-8"))


def test_write_replaces_existing_file(set_workspace):
    target = set_workspace / "out.txt"
    target.write_text("old", encoding="utf-8")

    result = run_async(FileSystemWrite().execute({"path": str(target), "content": "new"}))
    assert result.success is True
    assert target.read_text(encoding="utf-8") == "new"


def test_write_outside_workspace_rejected(set_workspace, tmp_path):
    outside = tmp_path.parent / "unrelated_ws"
    outside.mkdir(exist_ok=True)
    target = outside / "evil.txt"
    result = run_async(
        FileSystemWrite().execute({"path": str(target), "content": "x"})
    )
    assert result.success is False
    assert "outside approved workspace" in result.error
    assert not target.exists()


def test_write_to_directory_path_fails(set_workspace):
    (set_workspace / "sub").mkdir()
    result = run_async(
        FileSystemWrite().execute({"path": str(set_workspace / "sub"), "content": "x"})
    )
    assert result.success is False


def test_write_auto_creates_parent_directories(set_workspace):
    target = set_workspace / "deep" / "nested" / "file.txt"
    result = run_async(
        FileSystemWrite().execute({"path": str(target), "content": "deep"})
    )
    assert result.success is True
    assert target.read_text(encoding="utf-8") == "deep"


def test_write_validate_input():
    tool = FileSystemWrite()
    with pytest.raises(ValueError):
        tool.validate_input({})
    with pytest.raises(ValueError):
        tool.validate_input({"path": "x"})
    with pytest.raises(ValueError):
        tool.validate_input({"path": 42, "content": "x"})
    with pytest.raises(ValueError):
        tool.validate_input({"path": "x", "content": 42})


# ---------------------------------------------------------------------------
# metadata checks
# ---------------------------------------------------------------------------

def test_filesystem_tools_registry():
    from app.services.tools import TOOLS

    names = [tool.name for tool in TOOLS]
    assert names == [
        "filesystem.list",
        "filesystem.read",
        "filesystem.write",
        "shell.run",
        "git.status",
        "git.diff",
    ]
    for tool in TOOLS:
        assert tool.validate_scope  # concrete tool instances


def test_filesystem_tools_declared_metadata():
    tool_map = {t.name: t for t in FILESYSTEM_TOOLS}
    assert set(tool_map) == {"filesystem.list", "filesystem.read", "filesystem.write"}
    assert tool_map["filesystem.list"].risk_level == "LOW"
    assert tool_map["filesystem.write"].risk_level == "MEDIUM"
    assert tool_map["filesystem.write"].audit_level == "redacted"
    assert tool_map["filesystem.read"].audit_level == "redacted"