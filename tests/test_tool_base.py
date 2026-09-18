from __future__ import annotations

import asyncio

import pytest

from app.services.tools.base import Tool, ToolResult


# ---------------------------------------------------------------------------
# ToolResult (Pydantic model) tests
# ---------------------------------------------------------------------------

def test_tool_result_defaults():
    result = ToolResult(success=True)
    assert result.success is True
    assert result.output is None
    assert result.error is None
    assert result.metadata == {}


def test_tool_result_full_construction():
    result = ToolResult(
        success=False,
        output={"line": 10, "text": "hello"},
        error="permission denied",
        metadata={"tool": "filesystem.write"},
    )
    assert result.success is False
    assert result.output["line"] == 10
    assert result.error == "permission denied"
    assert result.metadata["tool"] == "filesystem.write"


def test_tool_result_serialise_round_trip():
    result = ToolResult(success=True, output=42)
    dumped = result.model_dump()
    restored = ToolResult.model_validate(dumped)
    assert restored.output == 42


# ---------------------------------------------------------------------------
# Tool (ABC) — enforce subclass contract
# ---------------------------------------------------------------------------

class _DummyTool(Tool):
    name = "dummy.test"
    purpose = "test tool"
    risk_level = "LOW"
    allowed_scope = ["/tmp"]

    async def _execute(self, input_data):
        return ToolResult(success=True, output="done")

    def validate_input(self, data):
        if "value" not in data:
            raise ValueError("missing 'value'")


def test_tool_concrete_execute():
    tool = _DummyTool()
    result = asyncio.run(tool.execute({"value": 1}))
    assert result.success is True
    assert result.output == "done"


def test_tool_validate_input_accepts_valid():
    _DummyTool().validate_input({"value": 1})


def test_tool_validate_input_raises_on_missing():
    with pytest.raises(ValueError):
        _DummyTool().validate_input({})


def test_abstract_tool_cannot_be_instantiated():
    with pytest.raises(TypeError):
        Tool()  # type: ignore[abstract]


# ---------------------------------------------------------------------------
# validate_scope — check allowed workspaces from config.yaml
# ---------------------------------------------------------------------------

class _ScopeTool(Tool):
    name = "scope.test"
    purpose = "scope checker"
    risk_level = "LOW"
    allowed_scope = []

    async def _execute(self, input_data):
        return ToolResult(success=True)

    def validate_input(self, data):
        pass


def test_validate_scope_inside_workspace(tmp_path, monkeypatch):
    tool = _ScopeTool()
    # Point config to a temp workspace
    from app.config.settings import AppConfig
    import app.services.tools.base as base_mod

    monkeypatch.setattr(base_mod.config, "workspace_paths", [str(tmp_path)])
    assert tool.validate_scope(str(tmp_path / "file.txt")) is True


def test_validate_scope_at_workspace_root(tmp_path, monkeypatch):
    tool = _ScopeTool()
    import app.services.tools.base as base_mod

    monkeypatch.setattr(base_mod.config, "workspace_paths", [str(tmp_path)])
    assert tool.validate_scope(str(tmp_path)) is True


def test_validate_scope_outside_workspace(tmp_path, monkeypatch):
    tool = _ScopeTool()
    workspace = tmp_path / "ws"
    workspace.mkdir()
    outside = tmp_path / "other"
    outside.mkdir()
    import app.services.tools.base as base_mod

    monkeypatch.setattr(base_mod.config, "workspace_paths", [str(workspace)])
    assert tool.validate_scope(str(outside / "secret.txt")) is False


def test_validate_scope_sibling_prefix_not_confused(tmp_path, monkeypatch):
    """Path with a similar prefix but not a child must be rejected."""
    workspace = tmp_path / "project"
    workspace.mkdir()
    sibling = tmp_path / "project2"
    sibling.mkdir()
    import app.services.tools.base as base_mod

    monkeypatch.setattr(base_mod.config, "workspace_paths", [str(workspace)])
    tool = _ScopeTool()
    assert tool.validate_scope(str(sibling / "evil.txt")) is False


def test_validate_scope_no_workspaces_configured(tmp_path, monkeypatch):
    import app.services.tools.base as base_mod

    monkeypatch.setattr(base_mod.config, "workspace_paths", [])
    tool = _ScopeTool()
    assert tool.validate_scope(str(tmp_path / "anything.txt")) is False
