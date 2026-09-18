from __future__ import annotations

import difflib
from pathlib import Path
from typing import Any

from app.services.tools.base import Tool, ToolResult


class CodeEdit(Tool):
    name = "code.edit"
    purpose = "Edit code files with diff preview and approval (MEDIUM risk)"
    risk_level = "MEDIUM"
    allowed_scope: list[str] = []
    timeout_seconds = 30
    supports_dry_run = True
    audit_level = "full"

    def validate_input(self, data: dict[str, Any]) -> None:
        if "path" not in data:
            raise ValueError("Missing required field: path")
        if "edits" not in data:
            raise ValueError("Missing required field: edits")
        if not isinstance(data["path"], str):
            raise ValueError("path must be a string")

        edits = data["edits"]
        if isinstance(edits, dict):
            edits = [edits]
        elif not isinstance(edits, list):
            raise ValueError("edits must be a dict or list of dicts")

        if not edits:
            raise ValueError("edits cannot be empty")

        for edit in edits:
            if not isinstance(edit, dict):
                raise ValueError("each edit must be a dict with 'find' and 'replace'")
            if "find" not in edit:
                raise ValueError("Each edit must have 'find' field")
            if "replace" not in edit:
                raise ValueError("Each edit must have 'replace' field")
            if not isinstance(edit["find"], str) or not edit["find"]:
                raise ValueError("Each edit 'find' must be a non-empty string")
            if not isinstance(edit["replace"], str):
                raise ValueError("Each edit 'replace' must be a string")

        if data.get("dry_run") is not None and not isinstance(data["dry_run"], bool):
            raise ValueError("dry_run must be a boolean")

    def _compute_diff(self, original: str, modified: str, filename: str = "file") -> str:
        """Compute unified diff between original and modified content."""
        original_lines = original.splitlines(keepends=True)
        modified_lines = modified.splitlines(keepends=True)

        diff = list(
            difflib.unified_diff(
                original_lines,
                modified_lines,
                fromfile=f"a/{filename}",
                tofile=f"b/{filename}",
                n=3,
            )
        )

        return "".join(diff) if diff else ""

    def _apply_edits(self, content: str, edits: list[dict]) -> tuple[str, list[dict]]:
        """Apply edits to content and return modified content with edit results."""
        results: list[dict] = []
        modified_content = content

        for i, edit in enumerate(edits):
            find_str = edit["find"]
            replace_str = edit["replace"]

            if find_str not in modified_content:
                results.append(
                    {
                        "index": i,
                        "success": False,
                        "reason": "Pattern not found",
                        "find": find_str[:100],
                    }
                )
                continue

            new_content = modified_content.replace(find_str, replace_str, 1)

            if new_content == modified_content:
                results.append({"index": i, "success": False, "reason": "No change made"})
            else:
                results.append(
                    {
                        "index": i,
                        "success": True,
                        "chars_changed": abs(len(replace_str) - len(find_str)),
                        "find": find_str[:100],
                        "replace": replace_str[:100],
                    }
                )
                modified_content = new_content

        return modified_content, results

    async def _execute(self, input_data: dict[str, Any]) -> ToolResult:
        path = input_data["path"]
        edits = input_data["edits"]
        dry_run = input_data.get("dry_run", False)

        if not isinstance(edits, list):
            edits = [edits]

        if not self.validate_scope(path):
            return ToolResult(
                success=False,
                output=None,
                error=f"Path '{path}' is outside approved workspace",
            )

        try:
            file_path = Path(path)

            if not file_path.exists():
                return ToolResult(success=False, output=None, error=f"File not found: {path}")
            if not file_path.is_file():
                return ToolResult(success=False, output=None, error=f"Not a file: {path}")

            original_content = file_path.read_text(encoding="utf-8")

            modified_content, edit_results = self._apply_edits(original_content, edits)

            diff = self._compute_diff(original_content, modified_content, file_path.name)

            base_output = {
                "diff": diff,
                "original_size": len(original_content.encode("utf-8")),
                "new_size": len(modified_content.encode("utf-8")),
                "edit_results": edit_results,
                "edit_count": len(edit_results),
                "successful_edits": sum(1 for e in edit_results if e.get("success")),
            }

            failed = [r for r in edit_results if not r.get("success")]
            if failed:
                return ToolResult(
                    success=False,
                    output={**base_output, "changes_made": False},
                    error=f"{len(failed)} of {len(edits)} edits could not be applied",
                    metadata={
                        "path": str(file_path),
                        "audit_note": "Full diff in output, not logged separately",
                    },
                )

            if not diff.strip():
                return ToolResult(
                    success=True,
                    output={"changes_made": False, "reason": "Edits matched existing content exactly"},
                    metadata={"path": str(file_path)},
                )

            if dry_run:
                return ToolResult(
                    success=True,
                    output={**base_output, "changes_made": True},
                    metadata={
                        "path": str(file_path),
                        "mode": "dry_run",
                        "audit_note": "Full diff in output, not logged separately",
                    },
                )

            file_path.write_text(modified_content, encoding="utf-8")

            return ToolResult(
                success=True,
                output={**base_output, "changes_made": True},
                metadata={
                    "path": str(file_path),
                    "mode": "live",
                    "audit_note": "Full diff in output, not logged separately",
                },
            )
        except Exception as exc:
            return ToolResult(success=False, output=None, error=str(exc))