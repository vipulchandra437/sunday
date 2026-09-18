from __future__ import annotations

import asyncio
import subprocess

import pytest

import app.services.tools.base as base_mod
from app.services.tools.git_operations import GitCommit, GitPush


def _git(cwd, *args) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def run_async(coro):
    return asyncio.run(coro)


@pytest.fixture()
def git_repo(tmp_path, monkeypatch):
    """Minimal repo with one committed file and local user config."""
    monkeypatch.setattr(base_mod.config, "workspace_paths", [str(tmp_path)])

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "t@t.io")
    _git(repo, "config", "user.name", "Test")
    (repo / "tracked.txt").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", "tracked.txt")
    _git(repo, "commit", "-m", "initial")
    return repo


def _stage_change(repo, name: str = "new.txt", content: str = "new content\n"):
    (repo / name).write_text(content, encoding="utf-8")
    _git(repo, "add", name)
    return name


@pytest.fixture()
def git_repo_with_remote(tmp_path, monkeypatch, git_repo):
    """A repo paired with a bare 'origin' remote."""
    remote = tmp_path / "remote.git"
    _git(tmp_path, "init", "--bare", str(remote))
    _git(git_repo, "remote", "add", "origin", str(remote))
    return git_repo, remote


# ---------------------------------------------------------------------------
# git.commit — validate_input
# ---------------------------------------------------------------------------

def test_commit_validate_input():
    tool = GitCommit()
    with pytest.raises(ValueError):
        tool.validate_input({})
    with pytest.raises(ValueError):
        tool.validate_input({"repo_path": "x"})
    with pytest.raises(ValueError):
        tool.validate_input({"repo_path": "x", "message": 42})
    with pytest.raises(ValueError):
        tool.validate_input({"repo_path": "x", "message": "   "})
    with pytest.raises(ValueError):
        tool.validate_input({"repo_path": "x", "message": "ok", "dry_run": "yes"})


# ---------------------------------------------------------------------------
# git.commit — happy paths
# ---------------------------------------------------------------------------

def test_commit_dry_run_previews_without_committing(git_repo):
    _stage_change(git_repo, "feature.txt")
    start_sha = _git(git_repo, "rev-parse", "HEAD").stdout.strip()

    result = run_async(
        GitCommit().execute({"repo_path": str(git_repo), "message": "add feature", "dry_run": True})
    )
    assert result.success is True
    assert result.output["file_count"] == 1
    assert "feature.txt" in result.output["staged_files"]
    assert "new content" in result.output["preview"]
    assert result.output["message"] == "add feature"

    # Nothing committed
    assert _git(git_repo, "rev-parse", "HEAD").stdout.strip() == start_sha
    log_lines = [ln for ln in _git(git_repo, "log", "--oneline").stdout.splitlines() if ln]
    assert len(log_lines) == 1  # only "initial"


def test_commit_live(git_repo):
    _stage_change(git_repo, "feature.txt")
    start_sha = _git(git_repo, "rev-parse", "HEAD").stdout.strip()

    result = run_async(
        GitCommit().execute({"repo_path": str(git_repo), "message": "add feature"})
    )
    assert result.success is True
    assert result.output["files_changed"] == 1
    assert len(result.output["commit_hash"]) == 7
    assert result.metadata["mode"] == "live"

    new_sha = _git(git_repo, "rev-parse", "HEAD").stdout.strip()
    assert new_sha != start_sha
    assert new_sha.startswith(result.output["commit_hash"])
    assert _git(git_repo, "log", "-1", "--pretty=%s").stdout.strip() == "add feature"


def test_commit_no_staged_changes(git_repo):
    result = run_async(
        GitCommit().execute({"repo_path": str(git_repo), "message": "nothing"})
    )
    assert result.success is False
    assert "No staged changes" in result.error


def test_commit_outside_workspace(tmp_path, monkeypatch):
    outside = tmp_path.parent / "other_ws"
    outside.mkdir(exist_ok=True)
    monkeypatch.setattr(base_mod.config, "workspace_paths", [str(tmp_path)])
    result = run_async(
        GitCommit().execute({"repo_path": str(outside), "message": "x"})
    )
    assert result.success is False
    assert "outside approved workspace" in result.error


def test_commit_not_a_repo(tmp_path, monkeypatch):
    monkeypatch.setattr(base_mod.config, "workspace_paths", [str(tmp_path)])
    not_repo = tmp_path / "not_repo"
    not_repo.mkdir()
    result = run_async(
        GitCommit().execute({"repo_path": str(not_repo), "message": "x"})
    )
    assert result.success is False
    assert result.error


# ---------------------------------------------------------------------------
# git.push — validate_input
# ---------------------------------------------------------------------------

def test_push_validate_input():
    tool = GitPush()
    with pytest.raises(ValueError):
        tool.validate_input({})
    with pytest.raises(ValueError):
        tool.validate_input({"repo_path": 42})
    with pytest.raises(ValueError):
        tool.validate_input({"repo_path": "x", "remote": 42})
    with pytest.raises(ValueError):
        tool.validate_input({"repo_path": "x", "branch": 42})
    with pytest.raises(ValueError):
        tool.validate_input({"repo_path": "x", "dry_run": "yes"})


# ---------------------------------------------------------------------------
# git.push — happy paths
# ---------------------------------------------------------------------------

def test_push_dry_run_shows_ahead(git_repo_with_remote):
    repo, remote = git_repo_with_remote
    # Establish the remote and fetch it so origin/main exists locally
    _git(repo, "push", "origin", "main")
    _git(repo, "fetch", "origin")
    _stage_change(repo, "feature.txt")
    _git(repo, "commit", "-m", "feature")

    result = run_async(
        GitPush().execute({"repo_path": str(repo), "dry_run": True})
    )
    assert result.success is True
    assert result.output["remote"] == "origin"
    assert result.output["branch"] == "main"
    assert result.output["ahead"] == 1
    assert result.metadata["mode"] == "dry_run"

    # Nothing pushed to the bare remote yet (still one commit behind)
    local_head = _git(repo, "rev-parse", "HEAD").stdout.strip()
    remote_head = _git(remote, "rev-parse", "main").stdout.strip()
    assert remote_head != local_head


def test_push_dry_run_without_upstream(git_repo_with_remote):
    repo, _ = git_repo_with_remote
    _stage_change(repo, "feature.txt")
    _git(repo, "commit", "-m", "feature")

    result = run_async(
        GitPush().execute({"repo_path": str(repo), "dry_run": True})
    )
    assert result.success is True
    assert result.output["ahead"] is None  # unknown until a fetch happens
    assert result.output["has_upstream"] is False


def test_push_live(git_repo_with_remote):
    repo, remote = git_repo_with_remote
    _stage_change(repo, "feature.txt")
    _git(repo, "commit", "-m", "feature")

    result = run_async(GitPush().execute({"repo_path": str(repo)}))
    assert result.success is True
    assert result.output["pushed"] is True
    assert result.output["branch"] == "main"

    # Remote now has the local commit
    local_head = _git(repo, "rev-parse", "HEAD").stdout.strip()
    remote_head = _git(remote, "rev-parse", "main").stdout.strip()
    assert remote_head == local_head


def test_push_up_to_date(git_repo_with_remote):
    repo, _ = git_repo_with_remote
    run_async(GitPush().execute({"repo_path": str(repo)}))

    result = run_async(GitPush().execute({"repo_path": str(repo)}))
    assert result.success is True
    assert result.output["pushed"] is False


def test_push_outside_workspace(tmp_path, monkeypatch):
    outside = tmp_path.parent / "other_ws"
    outside.mkdir(exist_ok=True)
    monkeypatch.setattr(base_mod.config, "workspace_paths", [str(tmp_path)])
    result = run_async(GitPush().execute({"repo_path": str(outside)}))
    assert result.success is False
    assert "outside approved workspace" in result.error


def test_push_remote_not_found(git_repo):
    result = run_async(GitPush().execute({"repo_path": str(git_repo)}))
    assert result.success is False
    assert "Remote 'origin' not found" in result.error


def test_push_dry_run_reports_remote_url(git_repo_with_remote):
    repo, _ = git_repo_with_remote
    result = run_async(GitPush().execute({"repo_path": str(repo), "dry_run": True}))
    assert result.success is True
    assert result.output["remote_url"].endswith("remote.git")


def test_tool_metadata():
    assert GitCommit().supports_dry_run is True
    assert GitCommit().risk_level == "MEDIUM"
    assert GitPush().supports_dry_run is True
    assert GitPush().risk_level == "MEDIUM"
    assert GitPush().timeout_seconds == 60