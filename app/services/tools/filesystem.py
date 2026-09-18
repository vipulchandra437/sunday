from __future__ import annotations

from pathlib import Path
from typing import Any

from app.services.tools.base import Tool, ToolResult


class FileSystemList(Tool):
    name = "filesystem.list"
    purpose = "List files and folders in an approved directory"
    risk_level = "LOW"
    allowed_scope: list[str] = []
    audit_level = "full"

    def validate_input(self, data: dict[str, Any]) -> None:
        if "path" not in data:
            raise ValueError("Missing required field: path")
        if not isinstance(data["path"], str):
            raise ValueError("path must be a string")

    async def _execute(self, input_data: dict[str, Any]) -> ToolResult:
        path = input_data["path"]

        if not self.validate_scope(path):
            return ToolResult(
                success=False,
                error=f"Path '{path}' is outside approved workspace",
            )

        try:
            dir_path = Path(path)
            if not dir_path.exists():
                return ToolResult(success=False, error=f"Path '{path}' does not exist")
            if not dir_path.is_dir():
                return ToolResult(success=False, error=f"Path '{path}' is not a directory")

            entries = [
                {
                    "name": item.name,
                    "type": "directory" if item.is_dir() else "file",
                    "size": item.stat().st_size if item.is_file() else 0,
                }
                for item in dir_path.iterdir()
            ]
            return ToolResult(
                success=True,
                output=entries,
                metadata={"count": len(entries)},
            )
        except OSError as exc:
            return ToolResult(success=False, error=str(exc))


class FileSystemRead(Tool):
    name = "filesystem.read"
    purpose = "Read file content from approved workspace"
    risk_level = "LOW"
    allowed_scope: list[str] = []
    audit_level = "redacted"  # Don't log file contents

    def validate_input(self, data: dict[str, Any]) -> None:
        if "path" not in data:
            raise ValueError("Missing required field: path")
        if not isinstance(data["path"], str):
            raise ValueError("path must be a string")

    async def _execute(self, input_data: dict[str, Any]) -> ToolResult:
        path = input_data["path"]

        if not self.validate_scope(path):
            return ToolResult(
                success=False,
                output=None,
                error=f"Path '{path}' is outside approved workspace",
            )

        try:
            file_path = Path(path)

            if not file_path.exists():
                return ToolResult(
                    success=False,
                    output=None,
                    error=f"File not found: {path}",
                )

            if not file_path.is_file():
                return ToolResult(
                    success=False,
                    output=None,
                    error=f"Not a file: {path}",
                )

            content = file_path.read_text(encoding="utf-8")

            return ToolResult(
                success=True,
                output={
                    "content": content,
                    "size": len(content.encode("utf-8")),
                    "lines": len(content.splitlines()),
                },
                metadata={"path": str(file_path)},
            )
        except Exception as exc:
            return ToolResult(success=False, output=None, error=str(exc))


class FileSystemWrite(Tool):
    name = "filesystem.write"
    purpose = "Write content to file in approved workspace"
    risk_level = "MEDIUM"  # Requires approval per policy
    allowed_scope: list[str] = []
    audit_level = "redacted"  # Don't log file contents
    timeout_seconds = 60

    def validate_input(self, data: dict[str, Any]) -> None:
        if "path" not in data:
            raise ValueError("Missing required field: path")
        if "content" not in data:
            raise ValueError("Missing required field: content")
        if not isinstance(data["path"], str):
            raise ValueError("path must be a string")
        if not isinstance(data["content"], str):
            raise ValueError("content must be a string")

    async def _execute(self, input_data: dict[str, Any]) -> ToolResult:
        path = input_data["path"]
        content = input_data["content"]

        if not self.validate_scope(path):
            return ToolResult(
                success=False,
                output=None,
                error=f"Path '{path}' is outside approved workspace",
            )

        try:
            file_path = Path(path)
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")

            return ToolResult(
                success=True,
                output={"size": len(content.encode("utf-8"))},
                metadata={"path": str(file_path)},
            )
        except Exception as exc:
            return ToolResult(success=False, output=None, error=str(exc))


FILESYSTEM_TOOLS = [FileSystemList, FileSystemRead, FileSystemWrite]