from __future__ import annotations

import asyncio
from typing import Any

from app.services.tools.base import Tool, ToolResult


async def _run_git(
    repo_path: str, timeout_seconds: int, *args: str
) -> tuple[int, str, str]:
    """Run a git command and return (returncode, stdout, stderr)."""
    proc = await asyncio.create_subprocess_exec(
        "git", *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=repo_path,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(),
            timeout=timeout_seconds,
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise
    return (
        proc.returncode,
        stdout.decode("utf-8", errors="replace"),
        stderr.decode("utf-8", errors="replace"),
    )


class GitCommit(Tool):
    name = "git.commit"
    purpose = "Commit staged changes to Git repository (requires approval)"
    risk_level = "MEDIUM"
    allowed_scope: list[str] = []
    timeout_seconds = 30
    supports_dry_run = True  # Preview commit before actual execution
    audit_level = "full"

    def validate_input(self, data: dict[str, Any]) -> None:
        if "repo_path" not in data:
            raise ValueError("Missing required field: repo_path")
        if "message" not in data:
            raise ValueError("Missing required field: message")
        if not isinstance(data["repo_path"], str):
            raise ValueError("repo_path must be a string")
        if not isinstance(data["message"], str):
            raise ValueError("message must be a string")
        if len(data["message"].strip()) == 0:
            raise ValueError("Commit message cannot be empty")
        if data.get("dry_run") is not None and not isinstance(data["dry_run"], bool):
            raise ValueError("dry_run must be a boolean")

    async def _get_staged_files(self, repo_path: str) -> tuple[list[str], str]:
        """Get list of staged files and diff preview."""
        try:
            returncode, stdout, stderr = await _run_git(
                repo_path, self.timeout_seconds, "diff", "--cached", "--name-only"
            )
            if returncode != 0:
                return [], f"Git status failed: {stderr}"

            files = [line.strip() for line in stdout.splitlines() if line.strip()]
            return files, ""
        except Exception as exc:
            return [], str(exc)

    async def _get_commit_preview(self, repo_path: str) -> str:
        """Get the actual diff that will be committed."""
        try:
            returncode, stdout, stderr = await _run_git(
                repo_path, self.timeout_seconds, "diff", "--cached"
            )
            if returncode != 0:
                return f"Preview failed: {stderr}"

            diff = stdout
            # Truncate if too large
            if len(diff.encode("utf-8")) > 10240:
                diff = diff[:10240] + "\n...[TRUNCATED]"

            return diff
        except Exception as exc:
            return f"Preview error: {str(exc)}"

    async def _execute(self, input_data: dict[str, Any]) -> ToolResult:
        repo_path = input_data["repo_path"]
        message = input_data["message"]
        dry_run = input_data.get("dry_run", False)

        # Validate scope
        if not self.validate_scope(repo_path):
            return ToolResult(
                success=False,
                output=None,
                error=f"Repository path '{repo_path}' is outside approved workspace",
            )

        # Get staged files and preview
        staged_files, error = await self._get_staged_files(repo_path)
        if error:
            return ToolResult(success=False, output=None, error=error)

        if not staged_files:
            return ToolResult(
                success=False,
                output=None,
                error="No staged changes to commit",
            )

        # Get full diff for preview
        diff_preview = await self._get_commit_preview(repo_path)

        if dry_run:
            return ToolResult(
                success=True,
                output={
                    "staged_files": staged_files,
                    "file_count": len(staged_files),
                    "preview": diff_preview,
                    "message": message,
                },
                metadata={"mode": "dry_run", "repo_path": repo_path},
            )

        # Actually perform the commit
        try:
            returncode, stdout, stderr = await _run_git(
                repo_path, self.timeout_seconds, "commit", "-m", message
            )

            if returncode != 0:
                return ToolResult(
                    success=False,
                    output=None,
                    error=f"Git commit failed: {stderr}",
                )

            first_line = stdout.strip().splitlines()[0] if stdout.strip() else ""
            commit_hash = first_line.split("]")[0].split()[-1] if first_line else ""

            return ToolResult(
                success=True,
                output={
                    "commit_hash": commit_hash,
                    "files_changed": len(staged_files),
                    "message": message,
                },
                metadata={
                    "mode": "live",
                    "repo_path": repo_path,
                    "staged_files": staged_files,
                },
            )
        except asyncio.TimeoutError:
            return ToolResult(
                success=False,
                output=None,
                error=f"Git commit timed out after {self.timeout_seconds}s",
            )
        except Exception as exc:
            return ToolResult(success=False, output=None, error=str(exc))


class GitPush(Tool):
    name = "git.push"
    purpose = "Push local commits to a remote branch (requires approval)"
    risk_level = "MEDIUM"
    allowed_scope: list[str] = []
    timeout_seconds = 60
    supports_dry_run = True  # Show what would be pushed without pushing
    audit_level = "full"

    def validate_input(self, data: dict[str, Any]) -> None:
        if "repo_path" not in data:
            raise ValueError("Missing required field: repo_path")
        if not isinstance(data["repo_path"], str):
            raise ValueError("repo_path must be a string")
        if data.get("remote") is not None and not isinstance(data["remote"], str):
            raise ValueError("remote must be a string")
        if data.get("branch") is not None and not isinstance(data["branch"], str):
            raise ValueError("branch must be a string")
        if data.get("dry_run") is not None and not isinstance(data["dry_run"], bool):
            raise ValueError("dry_run must be a boolean")

    async def _execute(self, input_data: dict[str, Any]) -> ToolResult:
        repo_path = input_data["repo_path"]
        remote = input_data.get("remote", "origin")
        branch = input_data.get("branch")
        dry_run = input_data.get("dry_run", False)

        if not self.validate_scope(repo_path):
            return ToolResult(
                success=False,
                output=None,
                error=f"Repository path '{repo_path}' is outside approved workspace",
            )

        try:
            returncode, stdout, _ = await _run_git(
                repo_path, self.timeout_seconds, "remote", "get-url", remote
            )
            if returncode != 0:
                return ToolResult(
                    success=False,
                    output=None,
                    error=f"Remote '{remote}' not found",
                )
            remote_url = stdout.strip()

            if branch is None:
                returncode, stdout, stderr = await _run_git(
                    repo_path, self.timeout_seconds, "rev-parse", "--abbrev-ref", "HEAD"
                )
                if returncode != 0:
                    return ToolResult(success=False, output=None, error=f"Git failed: {stderr}")
                branch = stdout.strip()

            # Determine upstream state
            upstream_ref = f"{remote}/{branch}"
            returncode, _, _ = await _run_git(
                repo_path, self.timeout_seconds, "rev-parse", "--verify", upstream_ref
            )
            has_upstream = returncode == 0

            ahead: int | None = None
            if has_upstream:
                returncode, stdout, _ = await _run_git(
                    repo_path,
                    self.timeout_seconds,
                    "rev-list", "--count", f"{upstream_ref}..HEAD",
                )
                if returncode == 0:
                    ahead = int(stdout.strip() or 0)

            if dry_run:
                return ToolResult(
                    success=True,
                    output={
                        "remote": remote,
                        "branch": branch,
                        "ahead": ahead,
                        "has_upstream": has_upstream,
                        "pushed": False,
                        "remote_url": remote_url,
                    },
                    metadata={"mode": "dry_run", "repo_path": repo_path},
                )

            returncode, stdout, stderr = await _run_git(
                repo_path, self.timeout_seconds, "push", remote, branch
            )
            if returncode != 0:
                return ToolResult(
                    success=False,
                    output=None,
                    error=f"Git push failed: {stderr or stdout}",
                )

            message = (stdout or "") + (stderr or "")
            up_to_date = (
                "everything up-to-date" in message.lower()
                or "up to date" in message.lower()
                or "already up to date" in message.lower()
            )

            return ToolResult(
                success=True,
                output={
                    "pushed": not up_to_date,
                    "remote": remote,
                    "branch": branch,
                    "ahead": 0 if up_to_date else (ahead or 0),
                },
                metadata={
                    "mode": "live",
                    "repo_path": repo_path,
                    "remote_url": remote_url,
                },
            )
        except asyncio.TimeoutError:
            return ToolResult(
                success=False,
                output=None,
                error=f"Git push timed out after {self.timeout_seconds}s",
            )
        except Exception as exc:
            return ToolResult(success=False, output=None, error=str(exc))