from __future__ import annotations

import asyncio

import pytest

import app.services.tools.base as base_mod
from app.services.tools.code_edit import CodeEdit


def run_async(coro):
    return asyncio.run(coro)


@pytest.fixture()
def workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(base_mod.config, "workspace_paths", [str(tmp_path)])
    return tmp_path


@pytest.fixture()
def sample_file(workspace):
    p = workspace / "sample.py"
    p.write_text("def foo():\n    return 1\n", encoding="utf-8")
    return p


def _edit(path, **overrides):
    return {"path": str(path), "edits": {"find": "return 1", "replace": "return 2"}, **overrides}


# ---------------------------------------------------------------------------
# code.edit — validate_input
# ---------------------------------------------------------------------------

def test_validate_input():
    tool = CodeEdit()
    with pytest.raises(ValueError):
        tool.validate_input({})
    with pytest.raises(ValueError):
        tool.validate_input({"path": "x"})
    with pytest.raises(ValueError):
        tool.validate_input({"edits": [{"find": "a", "replace": "b"}]})
    with pytest.raises(ValueError):
        tool.validate_input({"path": 42, "edits": [{"find": "a", "replace": "b"}]})
    with pytest.raises(ValueError):
        tool.validate_input({"path": "x", "edits": "oops"})
    with pytest.raises(ValueError):
        tool.validate_input({"path": "x", "edits": []})
    with pytest.raises(ValueError):
        tool.validate_input({"path": "x", "edits": [{"replace": "b"}]})
    with pytest.raises(ValueError):
        tool.validate_input({"path": "x", "edits": [{"find": "a"}]})
    with pytest.raises(ValueError):
        tool.validate_input({"path": "x", "edits": ["not-a-dict"]})
    with pytest.raises(ValueError):
        tool.validate_input({"path": "x", "edits": [{"find": "", "replace": "b"}]})
    with pytest.raises(ValueError):
        tool.validate_input({"path": "x", "edits": [{"find": "a", "replace": "b"}], "dry_run": "yes"})


def test_tool_metadata():
    tool = CodeEdit()
    assert tool.name == "code.edit"
    assert tool.risk_level == "MEDIUM"
    assert tool.supports_dry_run is True


# ---------------------------------------------------------------------------
# code.edit — dry run
# ---------------------------------------------------------------------------

def test_dry_run_previews_without_writing(sample_file):
    original = sample_file.read_text(encoding="utf-8")
    result = run_async(CodeEdit().execute(_edit(sample_file, dry_run=True)))
    assert result.success is True
    assert result.output["changes_made"] is True
    assert "return 1" in result.output["diff"]
    assert "return 2" in result.output["diff"]
    assert result.output["successful_edits"] == 1
    assert result.metadata["mode"] == "dry_run"
    assert sample_file.read_text(encoding="utf-8") == original


# ---------------------------------------------------------------------------
# code.edit — live execution
# ---------------------------------------------------------------------------

def test_live_edit_writes_file(sample_file):
    result = run_async(CodeEdit().execute(_edit(sample_file)))
    assert result.success is True
    assert result.output["changes_made"] is True
    assert result.output["successful_edits"] == 1
    assert result.metadata["mode"] == "live"
    assert "return 2" in sample_file.read_text(encoding="utf-8")
    assert "return 1" not in sample_file.read_text(encoding="utf-8")


def test_edit_dict_single_form(sample_file):
    result = run_async(CodeEdit().execute(_edit(sample_file)))
    assert result.success is True
    assert result.output["edit_count"] == 1


def test_multiple_edits_all_applied(sample_file):
    edits = [
        {"find": "return 1", "replace": "return 2"},
        {"find": "def foo", "replace": "def bar"},
    ]
    result = run_async(CodeEdit().execute({"path": str(sample_file), "edits": edits}))
    assert result.success is True
    assert result.output["edit_count"] == 2
    assert result.output["successful_edits"] == 2
    content = sample_file.read_text(encoding="utf-8")
    assert "return 2" in content
    assert "def bar" in content


# ---------------------------------------------------------------------------
# code.edit — failure paths
# ---------------------------------------------------------------------------

def test_pattern_not_found_blocks_write(sample_file):
    original = sample_file.read_text(encoding="utf-8")
    result = run_async(
        CodeEdit().execute({"path": str(sample_file), "edits": [{"find": "missing", "replace": "x"}]})
    )
    assert result.success is False
    assert "could not be applied" in result.error
    assert result.output["edit_results"][0]["success"] is False
    assert result.output["edit_results"][0]["reason"] == "Pattern not found"
    assert sample_file.read_text(encoding="utf-8") == original


def test_partial_failure_does_not_write(sample_file):
    original = sample_file.read_text(encoding="utf-8")
    edits = [
        {"find": "return 1", "replace": "return 2"},
        {"find": "missing", "replace": "x"},
    ]
    result = run_async(CodeEdit().execute({"path": str(sample_file), "edits": edits}))
    assert result.success is False
    assert result.output["successful_edits"] == 1
    assert sample_file.read_text(encoding="utf-8") == original


def test_no_change_when_find_equals_replace(sample_file):
    result = run_async(
        CodeEdit().execute({"path": str(sample_file), "edits": [{"find": "return 1", "replace": "return 1"}]})
    )
    assert result.success is False
    assert "could not be applied" in result.error


def test_file_not_found(workspace):
    result = run_async(
        CodeEdit().execute({"path": str(workspace / "nope.py"), "edits": [{"find": "a", "replace": "b"}]})
    )
    assert result.success is False
    assert "File not found" in result.error


def test_outside_workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(base_mod.config, "workspace_paths", [str(tmp_path)])
    outside = tmp_path.parent / "other.py"
    outside.write_text("x = 1\n", encoding="utf-8")
    result = run_async(
        CodeEdit().execute({"path": str(outside), "edits": [{"find": "x", "replace": "y"}]})
    )
    assert result.success is False
    assert "outside approved workspace" in result.error