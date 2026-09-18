from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

import app.services.tools.base as base_mod
from app.services.tools.test_runner import TestRunner


def run_async(coro):
    return asyncio.run(coro)


@pytest.fixture()
def workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(base_mod.config, "workspace_paths", [str(tmp_path)])
    monkeypatch.setitem(
        TestRunner.TEST_FRAMEWORKS["pytest"], "command", [sys.executable, "-m", "pytest"]
    )
    return tmp_path


@pytest.fixture()
def passing_project(workspace):
    (workspace / "test_sample.py").write_text(
        "def test_true():\n    assert True\n", encoding="utf-8"
    )
    return workspace


@pytest.fixture()
def failing_project(workspace):
    (workspace / "test_sample.py").write_text(
        "def test_false():\n    assert False\n", encoding="utf-8"
    )
    return workspace


def _run(framework, path, **overrides):
    return {"framework": framework, "path": str(path), **overrides}


# ---------------------------------------------------------------------------
# test.run — validate_input
# ---------------------------------------------------------------------------

def test_validate_input():
    tool = TestRunner()
    with pytest.raises(ValueError):
        tool.validate_input({})
    with pytest.raises(ValueError):
        tool.validate_input({"framework": "pytest"})
    with pytest.raises(ValueError):
        tool.validate_input({"framework": "pytest", "path": "x", "args": "oops"})
    with pytest.raises(ValueError):
        tool.validate_input({"framework": "pytest", "path": "x", "args": [1, 2]})


def test_validate_input_unsupported_framework():
    tool = TestRunner()
    with pytest.raises(ValueError, match="Unsupported framework: nose"):
        tool.validate_input({"framework": "nose", "path": "x"})


def test_validate_input_path_must_be_string():
    tool = TestRunner()
    with pytest.raises(ValueError):
        tool.validate_input({"framework": "pytest", "path": 42})


def test_validate_input_rejects_dry_run():
    tool = TestRunner()
    with pytest.raises(ValueError):
        tool.validate_input({"framework": "pytest", "path": "x", "dry_run": True})


def test_validate_input_arg_allowlist():
    tool = TestRunner()
    tool.validate_input({"framework": "pytest", "path": "x", "args": ["-q"]})
    tool.validate_input({"framework": "pytest", "path": "x", "args": ["-k", "test_pass"]})
    with pytest.raises(ValueError, match="not allowed"):
        tool.validate_input({"framework": "pytest", "path": "x", "args": ["--pdb"]})
    with pytest.raises(ValueError, match="not allowed"):
        tool.validate_input({"framework": "pytest", "path": "x", "args": ["--coverage"]})


def test_tool_metadata():
    tool = TestRunner()
    assert tool.name == "test.run"
    assert tool.risk_level == "MEDIUM"
    assert tool.supports_dry_run is False


# ---------------------------------------------------------------------------
# test.run — live execution
# ---------------------------------------------------------------------------

def test_pytest_success(passing_project):
    result = run_async(TestRunner().execute(_run("pytest", passing_project)))
    assert result.success is True
    assert result.output["return_code"] == 0
    parsed = result.output["parsed_results"]
    assert parsed["passed"] >= 1
    assert parsed["failed"] == 0
    assert 0 < parsed["success_rate"] <= 100
    assert result.output["duration_ms"] >= 0
    assert result.metadata["tests_passed"] >= 1
    assert result.metadata["tests_failed"] == 0
    assert not (passing_project / "test-results.xml").exists()


def test_pytest_failure(failing_project):
    result = run_async(TestRunner().execute(_run("pytest", failing_project)))
    assert result.success is False
    assert result.output["return_code"] != 0
    parsed = result.output["parsed_results"]
    assert parsed["failed"] >= 1
    assert result.metadata["tests_failed"] >= 1
    assert not (failing_project / "test-results.xml").exists()


def test_pytest_args_passthrough(passing_project):
    result = run_async(
        TestRunner().execute(_run("pytest", passing_project, args=["-k", "test_true"]))
    )
    assert result.success is True
    assert result.metadata["tests_passed"] >= 1
    assert "-k test_true" in result.output["command"]


def test_outside_workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(base_mod.config, "workspace_paths", [str(tmp_path)])
    outside = tmp_path.parent / "other_ws"
    outside.mkdir(exist_ok=True)
    result = run_async(TestRunner().execute(_run("pytest", outside)))
    assert result.success is False
    assert "outside approved workspace" in result.error


def test_not_a_directory(workspace):
    f = workspace / "notes.txt"
    f.write_text("hi\n", encoding="utf-8")
    result = run_async(TestRunner().execute(_run("pytest", f)))
    assert result.success is False
    assert "Not a directory" in result.error


def test_unsupported_framework_guard(workspace):
    result = run_async(TestRunner().execute({"framework": "nose", "path": str(workspace)}))
    assert result.success is False
    assert "Unsupported test framework" in result.error