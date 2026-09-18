from __future__ import annotations

import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.config.settings import config
from app.core.audit_service import audit_log


class ToolResult(BaseModel):
    """Standard return type for all tools."""

    success: bool
    output: Any | None = None
    error: str | None = Field(default=None)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Tool(ABC):
    """Base class for all Sunday tools."""

    name: str = ""
    purpose: str = ""
    risk_level: Literal["LOW", "MEDIUM", "HIGH"] = "LOW"
    allowed_scope: list[str] = []
    timeout_seconds: int = 30
    supports_dry_run: bool = False
    audit_level: Literal["minimal", "full", "redacted"] = "full"

    @abstractmethod
    async def _execute(self, input_data: dict[Any, Any]) -> ToolResult:
        """Execute the tool with validated input.

        Subclasses implement the actual tool logic here.
        """

    @abstractmethod
    def validate_input(self, data: dict[Any, Any]) -> None:
        """Validate input schema before execution.

        Raises ValueError on invalid input.
        """

    async def execute(self, input_data: dict[Any, Any]) -> ToolResult:
        """Template method: run the tool and record failures in the audit log."""
        try:
            result = await self._execute(input_data)
        except Exception as exc:
            result = ToolResult(success=False, output=None, error=str(exc))

        if not result.success:
            audit_log(
                event_type="tool_failure",
                data={"tool_name": self.name, "error": result.error},
            )

        return result

    def validate_scope(self, path: str) -> bool:
        """Check if path is within an approved workspace."""
        resolved = Path(os.path.abspath(path))

        workspaces = config.workspace_paths
        for workspace in workspaces:
            workspace_resolved = Path(os.path.abspath(workspace))
            try:
                resolved.relative_to(workspace_resolved)
            except ValueError:
                continue
            return True

        return False