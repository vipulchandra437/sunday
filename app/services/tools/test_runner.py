from __future__ import annotations

import asyncio
import xml.etree.ElementTree as ET
from pathlib import Path
from time import perf_counter
from typing import Any

from app.services.tools.base import Tool, ToolResult


class TestRunner(Tool):
    name = "test.run"
    purpose = "Run tests in approved workspace with result parsing (LOW/MEDIUM risk)"
    risk_level = "MEDIUM"
    allowed_scope: list[str] = []
    timeout_seconds = 120  # Tests can take time
    supports_dry_run = False
    audit_level = "full"

    TEST_FRAMEWORKS = {
        "pytest": {
            "command": ["python", "-m", "pytest"],
            "args_supported": ["-v", "--tb=short", "-q", "--collect-only", "-k", "--maxfail"],
            "results_parser": "pytest_xml",
        },
        "unittest": {
            "command": ["python", "-m", "unittest"],
            "args_supported": ["discover", "-v", "-q"],
            "results_parser": "unittest_xml",
        },
        "npm_test": {
            "command": ["npm", "test"],
            "args_supported": [],
            "results_parser": "npm_json",
        },
    }

    _TAKE_VALUE = {"-k", "--maxfail"}

    def _validate_args(self, framework: str, args: list[str]) -> None:
        allowed = set(self.TEST_FRAMEWORKS[framework]["args_supported"])
        for i, arg in enumerate(args):
            if arg in allowed:
                continue
            prev = args[i - 1] if i > 0 else None
            if prev in self._TAKE_VALUE:
                continue
            raise ValueError(f"Argument '{arg}' not allowed for {framework}")

    def validate_input(self, data: dict[str, Any]) -> None:
        if "framework" not in data:
            raise ValueError("Missing required field: framework")
        if "path" not in data:
            raise ValueError("Missing required field: path")

        if data["framework"] not in self.TEST_FRAMEWORKS:
            raise ValueError(
                f"Unsupported framework: {data['framework']}. Supported: {list(self.TEST_FRAMEWORKS)}"
            )

        if not isinstance(data["path"], str):
            raise ValueError("path must be a string")

        args = data.get("args")
        if args is not None:
            if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
                raise ValueError("args must be a list of strings")
            self._validate_args(data["framework"], args)

        if data.get("dry_run"):
            raise ValueError("dry_run not supported for test.run")

    def _parse_pytest_xml(self, xml_content: str) -> dict[str, Any]:
        """Parse pytest junit XML output."""
        try:
            root = ET.fromstring(xml_content)
            testsuites = root.findall(".//testsuite")
            if not testsuites:
                return {"error": "No testsuite element found", "raw": xml_content[:500]}
            testsuite = testsuites[0]

            total = int(testsuite.get("tests", 0))
            failures = int(testsuite.get("failures", 0))
            errors = int(testsuite.get("errors", 0))
            skipped = int(testsuite.get("skipped", 0))

            return {
                "total": total,
                "passed": total - failures - errors - skipped,
                "failed": failures,
                "errors": errors,
                "skipped": skipped,
                "duration_seconds": float(testsuite.get("time", 0)),
                "success_rate": (total - failures - errors - skipped) / total * 100 if total > 0 else 0,
            }
        except Exception:
            return {"error": "Failed to parse XML", "raw": xml_content[:500]}

    def _parse_unittest_xml(self, xml_content: str) -> dict[str, Any]:
        """Parse unittest junit XML output."""
        try:
            root = ET.fromstring(xml_content)
            if root.tag == "testsuites":
                testsuites = root.findall("testsuite")
                if not testsuites:
                    return {"error": "No testsuite element found", "raw": xml_content[:500]}
                root = testsuites[0]

            total = int(root.get("tests", 0))
            failures = int(root.get("failures", 0))
            errors = int(root.get("errors", 0))
            skipped = int(root.get("skipped", 0))

            return {
                "total": total,
                "passed": total - failures - errors - skipped,
                "failures": failures,
                "errors": errors,
                "skipped": skipped,
                "duration_seconds": float(root.get("time", 0)),
            }
        except Exception:
            return {"error": "Failed to parse XML", "raw": xml_content[:500]}

    async def _execute(self, input_data: dict[str, Any]) -> ToolResult:
        framework = input_data["framework"]
        path = input_data["path"]
        args = list(input_data.get("args") or [])

        if not self.validate_scope(path):
            return ToolResult(
                success=False,
                output=None,
                error=f"Path '{path}' is outside approved workspace",
            )
        if not Path(path).is_dir():
            return ToolResult(success=False, output=None, error=f"Not a directory: {path}")

        if framework not in self.TEST_FRAMEWORKS:
            return ToolResult(
                success=False,
                output=None,
                error=f"Unsupported test framework: {framework}",
            )

        config = self.TEST_FRAMEWORKS[framework]

        cmd = list(config["command"]) + args

        if framework == "pytest":
            cmd.append("--junitxml=test-results.xml")

        started = perf_counter()
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=path,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=self.timeout_seconds,
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return ToolResult(
                    success=False,
                    output=None,
                    error=f"Test run timed out after {self.timeout_seconds}s",
                )
            elapsed_ms = int((perf_counter() - started) * 1000)

            result_summary: dict[str, Any] = {
                "framework": framework,
                "command": " ".join(cmd),
                "return_code": proc.returncode,
                "stdout": stdout.decode("utf-8", errors="replace"),
                "stderr": stderr.decode("utf-8", errors="replace"),
                "duration_ms": elapsed_ms,
            }

            xml_path = Path(path) / "test-results.xml"
            try:
                if xml_path.exists():
                    xml_content = xml_path.read_text(encoding="utf-8")
                    if framework == "pytest":
                        result_summary["parsed_results"] = self._parse_pytest_xml(xml_content)
                    elif framework == "unittest":
                        result_summary["parsed_results"] = self._parse_unittest_xml(xml_content)
            finally:
                if xml_path.exists():
                    xml_path.unlink()

            parsed = result_summary.get("parsed_results") or {}
            return ToolResult(
                success=proc.returncode == 0,
                output=result_summary,
                metadata={
                    "path": path,
                    "framework": framework,
                    "tests_passed": parsed.get("passed", 0),
                    "tests_failed": parsed.get("failed", parsed.get("failures", 0)),
                },
            )
        except Exception as exc:
            return ToolResult(success=False, output=None, error=str(exc))