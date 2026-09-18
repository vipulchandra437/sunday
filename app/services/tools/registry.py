from __future__ import annotations

from typing import Any, Iterator

from app.services.tools.base import Tool


class ToolRegistry:
    """Central registry for tool instances and their permission policies."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        self._policies: dict[str, Any] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def register_all(self, tools: list[Tool]) -> None:
        for tool in tools:
            self.register(tool)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def require(self, name: str) -> Tool:
        tool = self._tools.get(name)
        if tool is None:
            raise KeyError(f"No tool registered: {name}")
        return tool

    def names(self) -> list[str]:
        return list(self._tools)

    def set_permission_policy(self, tool_name: str, policy: Any) -> None:
        self._policies[tool_name] = policy

    def permission_policy(self, tool_name: str) -> Any | None:
        return self._policies.get(tool_name)

    def __iter__(self) -> Iterator[Tool]:
        return iter(self._tools.values())

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools