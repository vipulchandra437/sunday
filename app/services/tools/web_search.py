from __future__ import annotations

from typing import Any

import httpx

from app.config.settings import settings
from app.services.tools.base import Tool, ToolResult

VALID_SAFESEARCH = ("off", "moderate", "strict")


class WebSearch(Tool):
    name = "web.search"
    purpose = "Search public web information via the Brave Search API"
    risk_level = "LOW"
    allowed_scope: list[str] = []
    timeout_seconds = 30
    supports_dry_run = False
    audit_level = "full"

    _base_url = "https://api.search.brave.com/res/v1/web/search"

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    def validate_input(self, data: dict[str, Any]) -> None:
        if "query" not in data:
            raise ValueError("Missing required field: query")
        if not isinstance(data["query"], str):
            raise ValueError("query must be a string")
        if not data["query"].strip():
            raise ValueError("query cannot be empty")
        if data.get("count") is not None:
            if not isinstance(data["count"], int):
                raise ValueError("count must be an integer")
            if not 1 <= data["count"] <= 20:
                raise ValueError("count must be between 1 and 20")
        if data.get("offset") is not None:
            if not isinstance(data["offset"], int):
                raise ValueError("offset must be an integer")
            if not 0 <= data["offset"] <= 9:
                raise ValueError("offset must be between 0 and 9")
        if data.get("safesearch") is not None and data["safesearch"] not in VALID_SAFESEARCH:
            raise ValueError("safesearch must be one of: off, moderate, strict")

    async def _execute(self, input_data: dict[str, Any]) -> ToolResult:
        query = input_data["query"].strip()
        count = input_data.get("count", 10)
        offset = input_data.get("offset", 0)
        safesearch = input_data.get("safesearch", "moderate")

        api_key = settings.brave_api_key
        if not api_key:
            return ToolResult(
                success=False,
                output=None,
                error="Brave API key is not set. Add BRAVE_API_KEY to the environment or .env.",
            )

        params = {"q": query, "count": count, "offset": offset, "safesearch": safesearch}
        headers = {
            "X-Subscription-Token": api_key,
            "Accept": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds, transport=self._transport) as client:
                response = await client.get(self._base_url, params=params, headers=headers)
                if response.status_code == 429:
                    return ToolResult(
                        success=False,
                        output=None,
                        error="Brave Search rate limit exceeded (HTTP 429). Try again later.",
                    )
                response.raise_for_status()
                data = response.json()
        except httpx.TimeoutException as exc:
            return ToolResult(
                success=False,
                output=None,
                error=f"Brave Search timed out after {self.timeout_seconds}s",
            )
        except httpx.HTTPStatusError as exc:
            return ToolResult(
                success=False,
                output=None,
                error=f"Brave Search request failed: HTTP {exc.response.status_code}",
            )
        except httpx.HTTPError as exc:
            return ToolResult(success=False, output=None, error=f"Brave Search request failed: {exc}")

        results = []
        for item in data.get("web", {}).get("results", [])[:count]:
            results.append(
                {
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "description": item.get("description", ""),
                }
            )

        return ToolResult(
            success=True,
            output={"query": query, "count": len(results), "results": results},
            metadata={"provider": "brave"},
        )