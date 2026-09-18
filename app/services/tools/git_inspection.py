from __future__ import annotations

import asyncio
from typing import Any

from app.services.tools.base import Tool, ToolResult


class GitStatus(Tool):
    name = "git.status"
    purpose = "Inspect Git repository state (modified/new/deleted files)"
    risk_level = "LOW"
    allowed_scope: list[str] = []
    timeout_seconds = 15
    audit_level = "full"

    def validate_input(self, data: dict[str, Any]) -> None:
        if "repo_path" not in data:
            raise ValueError("Missing required field: repo_path")
        if not isinstance(data["repo_path"], str):
            raise ValueError("repo_path must be a string")

    async def execute(self, input_data: dict[str, Any]) -> ToolResult:
        repo_path = input_data["repo_path"]

        if not self.validate_scope(repo_path):
            return ToolResult(
                success=False,
                output=None,
                error=f"Repository path '{repo_path}' is outside approved workspace",
            )

        try:
            proc = await asyncio.create_subprocess_exec(
                "git", "status", "--porcelain",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=repo_path,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=self.timeout_seconds,
                )

                if proc.returncode != 0:
                    return ToolResult(
                        success=False,
                        output=None,
                        error=f"Git failed: {stderr.decode('utf-8', errors='replace')}",
                    )

                lines = stdout.decode("utf-8").splitlines() if stdout else []
                modified: list[str] = []
                new: list[str] = []
                deleted: list[str] = []

                for line in lines:
                    if not line.strip():
                        continue

                    status_code = line[:2]
                    file_path = line[3:].strip()
                    index_state, worktree_state = status_code

                    if index_state in "MT" or worktree_state in "MT":
                        modified.append(file_path)
                    elif index_state in "A?" or worktree_state in "A?":
                        new.append(file_path)
                    elif index_state in "DR" or worktree_state in "DR":
                        deleted.append(file_path)

                return ToolResult(
                    success=True,
                    output={
                        "modified": modified,
                        "new": new,
                        "deleted": deleted,
                    },
                    metadata={
                        "total_changes": len(modified) + len(new) + len(deleted),
                        "repo_path": repo_path,
                    },
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return ToolResult(
                    success=False,
                    output=None,
                    error=f"Git status timed out after {self.timeout_seconds}s",
                )
        except Exception as exc:
            return ToolResult(success=False, output=None, error=str(exc))


class GitDiff(Tool):
    name = "git.diff"
    purpose = "Show Git diff compared to specified revision"
    risk_level = "LOW"
    allowed_scope: list[str] = []
    timeout_seconds = 30
    max_diff_size_bytes = 10240  # 10KB truncation limit
    audit_level = "full"

    def validate_input(self, data: dict[str, Any]) -> None:
        if "repo_path" not in data:
            raise ValueError("Missing required field: repo_path")
        if not isinstance(data["repo_path"], str):
            raise ValueError("repo_path must be a string")
        # target defaults to HEAD
        if "target" in data and not isinstance(data["target"], str):
            raise ValueError("target must be a string")

    async def execute(self, input_data: dict[str, Any]) -> ToolResult:
        repo_path = input_data["repo_path"]
        target = input_data.get("target", "HEAD")

        if not self.validate_scope(repo_path):
            return ToolResult(
                success=False,
                output=None,
                error=f"Repository path '{repo_path}' is outside approved workspace",
            )

        try:
            proc = await asyncio.create_subprocess_exec(
                "git", "diff", target,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=repo_path,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=self.timeout_seconds,
                )

                if proc.returncode not in (0, 1):  # 1 means differences found, OK
                    return ToolResult(
                        success=False,
                        output=None,
                        error=f"Git diff failed: {stderr.decode('utf-8', errors='replace')}",
                    )

                diff_content = stdout.decode("utf-8", errors="replace")
                truncated = False

                if len(diff_content.encode("utf-8")) > self.max_diff_size_bytes:
                    diff_content = diff_content[: self.max_diff_size_bytes] + "\n...[TRUNCATED]"
                    truncated = True

                # Count files changed (one 'diff --git' header per file)
                files_changed = sum(
                    1
                    for line in diff_content.split("\n")
                    if line.startswith("diff --git")
                )

                return ToolResult(
                    success=True,
                    output={
                        "diff": diff_content,
                        "files_changed": files_changed,
                        "truncated": truncated,
                    },
                    metadata={
                        "target": target,
                        "repo_path": repo_path,
                        "output_size_bytes": len(diff_content.encode("utf-8")),
                    },
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return ToolResult(
                    success=False,
                    output=None,
                    error=f"Git diff timed out after {self.timeout_seconds}s",
                )
        except Exception as exc:
            return ToolResult(success=False, output=None, error=str(exc))