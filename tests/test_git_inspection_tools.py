from __future__ import annotations

import asyncio
import subprocess

import pytest

import app.services.tools.base as base_mod
from app.services.tools.git_inspection import GitDiff, GitStatus


def _git(cwd, *args) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


@pytest.fixture()
def git_repo(tmp_path, monkeypatch):
    """Set up a tiny git repo with one committed file inside an approved workspace."""
    monkeypatch.setattr(base_mod.config, "workspace_paths", [str(tmp_path)])

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    (repo / "tracked.txt").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", "tracked.txt")
    _git(
        repo,
        "-c", "user.email=t@t.io",
        "-c", "user.name=Test",
        "commit", "-m", "initial",
    )
    return repo


def run_async(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# git.status — validate_input
# ---------------------------------------------------------------------------

def test_git_status_validate_input():
    tool = GitStatus()
    with pytest.raises(ValueError):
        tool.validate_input({})
    with pytest.raises(ValueError):
        tool.validate_input({"repo_path": 42})


# ---------------------------------------------------------------------------
# git.status — happy paths
# ---------------------------------------------------------------------------

def test_status_untracked_files(git_repo):
    (git_repo / "untracked.txt").write_text("new", encoding="utf-8")
    result = run_async(GitStatus().execute({"repo_path": str(git_repo)}))
    assert result.success is True
    assert "untracked.txt" in result.output["new"]
    assert result.metadata["total_changes"] == 1


def test_status_modified_files(git_repo):
    (git_repo / "tracked.txt").write_text("changed\n", encoding="utf-8")
    result = run_async(GitStatus().execute({"repo_path": str(git_repo)}))
    assert result.success is True
    assert "tracked.txt" in result.output["modified"]
    assert result.metadata["total_changes"] == 1


def test_status_deleted_files(git_repo):
    (git_repo / "tracked.txt").unlink()
    result = run_async(GitStatus().execute({"repo_path": str(git_repo)}))
    assert result.success is True
    assert "tracked.txt" in result.output["deleted"]
    assert result.metadata["total_changes"] == 1


def test_status_clean_repo(git_repo):
    result = run_async(GitStatus().execute({"repo_path": str(git_repo)}))
    assert result.success is True
    assert result.output == {"modified": [], "new": [], "deleted": []}
    assert result.metadata["total_changes"] == 0


def test_status_outside_workspace(tmp_path, monkeypatch):
    outside = tmp_path.parent / "unrelated_ws"
    outside.mkdir(exist_ok=True)
    monkeypatch.setattr(base_mod.config, "workspace_paths", [str(tmp_path)])
    result = run_async(GitStatus().execute({"repo_path": str(outside)}))
    assert result.success is False
    assert "outside approved workspace" in result.error


def test_status_not_a_git_repo(tmp_path, monkeypatch):
    monkeypatch.setattr(base_mod.config, "workspace_paths", [str(tmp_path)])
    non_repo = tmp_path / "not_a_repo"
    non_repo.mkdir()
    result = run_async(GitStatus().execute({"repo_path": str(non_repo)}))
    assert result.success is False
    assert "Git failed" in result.error


# ---------------------------------------------------------------------------
# git.diff — validate_input
# ---------------------------------------------------------------------------

def test_git_diff_validate_input():
    tool = GitDiff()
    with pytest.raises(ValueError):
        tool.validate_input({})
    with pytest.raises(ValueError):
        tool.validate_input({"repo_path": 42})
    with pytest.raises(ValueError):
        tool.validate_input({"repo_path": "x", "target": 42})


# ---------------------------------------------------------------------------
# git.diff — happy paths
# ---------------------------------------------------------------------------

def test_diff_shows_changes(git_repo):
    (git_repo / "tracked.txt").write_text("world\n", encoding="utf-8")
    result = run_async(GitDiff().execute({"repo_path": str(git_repo)}))
    assert result.success is True
    assert result.output["files_changed"] >= 1
    assert result.output["truncated"] is False
    assert "world" in result.output["diff"]
    assert result.metadata["target"] == "HEAD"
    assert result.metadata["output_size_bytes"] > 0


def test_diff_clean_repo(git_repo):
    result = run_async(GitDiff().execute({"repo_path": str(git_repo)}))
    assert result.success is True
    assert result.output["diff"] == ""
    assert result.output["files_changed"] == 0
    assert result.output["truncated"] is False
    assert result.metadata["output_size_bytes"] == 0


def test_diff_with_target_ref(git_repo):
    # Commit a second change so HEAD~1 exists
    (git_repo / "tracked.txt").write_text("second\n", encoding="utf-8")
    _git(git_repo, "add", "tracked.txt")
    _git(git_repo, "-c", "user.email=t@t.io", "-c", "user.name=Test",
         "commit", "-m", "second")
    sha = _git(git_repo, "rev-parse", "HEAD~1").stdout.strip()
    # Make a third change on top
    (git_repo / "tracked.txt").write_text("third\n", encoding="utf-8")

    # Default HEAD diff shows only third commit change
    result_default = run_async(GitDiff().execute({"repo_path": str(git_repo)}))
    assert result_default.success is True
    assert result_default.metadata["target"] == "HEAD"
    assert "third" in result_default.output["diff"]

    # Targeting the earlier commit shows both second + third changes vs that point
    result_prev = run_async(GitDiff().execute({"repo_path": str(git_repo), "target": sha}))
    assert result_prev.success is True
    assert result_prev.metadata["target"] == sha


def test_diff_truncates_large_output(git_repo):
    # Write > 10KB of content to trigger truncation
    big = "x" * 15000
    (git_repo / "tracked.txt").write_text(big, encoding="utf-8")
    result = run_async(GitDiff().execute({"repo_path": str(git_repo)}))
    assert result.success is True
    assert result.output["truncated"] is True
    assert "...[TRUNCATED]" in result.output["diff"]
    assert result.metadata["output_size_bytes"] > 0


def test_diff_outside_workspace(tmp_path, monkeypatch):
    outside = tmp_path.parent / "unrelated_ws"
    outside.mkdir(exist_ok=True)
    monkeypatch.setattr(base_mod.config, "workspace_paths", [str(tmp_path)])
    result = run_async(GitDiff().execute({"repo_path": str(outside)}))
    assert result.success is False
    assert "outside approved workspace" in result.error