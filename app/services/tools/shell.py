from __future__ import annotations

import asyncio
import re
from typing import Any

from app.services.tools.base import Tool, ToolResult


class ShellRun(Tool):
    name = "shell.run"
    purpose = "Execute safe shell commands in approved workspace"
    risk_level = "MEDIUM"
    allowed_scope: list[str] = []  # Uses cwd validation
    timeout_seconds = 30
    audit_level = "full"

    # Safe command allowlist
    SAFE_COMMANDS = {
        "ls", "cat", "grep", "echo", "pwd", "test", "mkdir", "rm", "cp", "mv",
        "git", "python", "npm", "pip", "head", "tail", "find", "chmod", "touch",
        "date", "whoami", "hostname",
    }

    # Dangerous patterns to block
    DANGEROUS_PATTERNS = [
        r"rm\s+-rf\s+/",
        r"rm\s+-rf\s+\*",
        r"rm\s+-[rf]{1,2}\s+(?:[a-zA-Z]:)?[\\/]",  # root/absolute deletes (incl. Windows C:\)
        r"rm\s+-[rf]{1,2}\s+\.\.?",              # rm -r/-f/-rf on . or .. (current/parent dir)
        r">\s*/dev/",
        r"\|\s*(sudo|su)\b",
        r"(curl|wget)\s+https?://[^ ]+",
        r"`[^`]+`",
        r"\$\([^)]+\)",
        r";\s*rm\s+",
        r"&&\s*rm\s+",
        r"\b(?:mkfs|fdisk|format)\b",
        r":\(\)\s*\{\s*[|&]",            # fork bomb
    ]

    def validate_input(self, data: dict[str, Any]) -> None:
        if "command" not in data:
            raise ValueError("Missing required field: command")
        if not isinstance(data["command"], str):
            raise ValueError("command must be a string")
        if data.get("cwd") and not isinstance(data["cwd"], str):
            raise ValueError("cwd must be a string")

    def _is_safe_command(self, command: str) -> tuple[bool, str]:
        """Check if command is in allowlist and doesn't contain dangerous patterns."""
        for pattern in self.DANGEROUS_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                return False, f"Blocked by security pattern: {pattern}"

        parts = command.strip().split()
        if not parts:
            return False, "Empty command"

        base_cmd = parts[0].lower()

        if base_cmd == "git":
            return True, "OK"

        if base_cmd == "python":
            return True, "OK"

        if base_cmd in ("npm", "pip"):
            return True, "OK"

        if base_cmd not in self.SAFE_COMMANDS:
            return False, f"Command '{base_cmd}' not in safe allowlist"

        return True, "OK"

    async def _execute(self, input_data: dict[str, Any]) -> ToolResult:
        command = input_data["command"]
        cwd = input_data.get("cwd", ".")

        is_safe, reason = self._is_safe_command(command)
        if not is_safe:
            return ToolResult(
                success=False,
                output=None,
                error=f"Command blocked: {reason}",
            )

        if not self.validate_scope(cwd):
            return ToolResult(
                success=False,
                output=None,
                error=f"Working directory '{cwd}' is outside approved workspace",
            )

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=self.timeout_seconds,
                )

                return ToolResult(
                    success=proc.returncode == 0,
                    output={
                        "stdout": stdout.decode("utf-8", errors="replace"),
                        "stderr": stderr.decode("utf-8", errors="replace"),
                        "return_code": proc.returncode,
                    },
                    metadata={"command": command, "cwd": cwd},
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return ToolResult(
                    success=False,
                    output=None,
                    error=f"Command timed out after {self.timeout_seconds}s",
                )
        except Exception as exc:
            return ToolResult(success=False, output=None, error=str(exc))