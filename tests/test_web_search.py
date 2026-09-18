from __future__ import annotations

import asyncio

import httpx
import pytest

from app.config.settings import settings
from app.services.tools.web_search import WebSearch


def run_async(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def brave_key(monkeypatch):
    monkeypatch.setattr(settings, "brave_api_key", "test-key")


def _json_handler(n_results: int, seen_params: dict | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if seen_params is not None:
            seen_params.update(request.url.params)
        assert request.url.params["q"] == "python asyncio"
        assert request.headers["X-Subscription-Token"] == "test-key"
        results = [
            {
                "title": f"Result {i}",
                "url": f"https://example.com/{i}",
                "description": f"Description {i}",
            }
            for i in range(n_results)
        ]
        return httpx.Response(200, json={"web": {"results": results}})

    return handler


# ---------------------------------------------------------------------------
# web.search — validate_input
# ---------------------------------------------------------------------------

def test_validate_input():
    tool = WebSearch()
    with pytest.raises(ValueError):
        tool.validate_input({})
    with pytest.raises(ValueError):
        tool.validate_input({"query": 42})
    with pytest.raises(ValueError):
        tool.validate_input({"query": "   "})
    with pytest.raises(ValueError):
        tool.validate_input({"query": "ok", "count": "three"})
    with pytest.raises(ValueError):
        tool.validate_input({"query": "ok", "count": 0})
    with pytest.raises(ValueError):
        tool.validate_input({"query": "ok", "count": 21})
    with pytest.raises(ValueError):
        tool.validate_input({"query": "ok", "offset": -1})
    with pytest.raises(ValueError):
        tool.validate_input({"query": "ok", "offset": 10})
    with pytest.raises(ValueError):
        tool.validate_input({"query": "ok", "safesearch": "extreme"})


def test_tool_metadata():
    tool = WebSearch()
    assert tool.name == "web.search"
    assert tool.risk_level == "LOW"
    assert tool.supports_dry_run is False


# ---------------------------------------------------------------------------
# web.search — happy paths
# ---------------------------------------------------------------------------

def test_search_returns_results():
    seen = {}
    tool = WebSearch(transport=httpx.MockTransport(_json_handler(3, seen)))
    result = run_async(
        tool.execute({"query": "python asyncio", "count": 3})
    )
    assert result.success is True
    assert seen["count"] == "3"
    assert seen["safesearch"] == "moderate"
    assert result.output["query"] == "python asyncio"
    assert result.output["count"] == 3
    assert result.output["results"][0] == {
        "title": "Result 0",
        "url": "https://example.com/0",
        "description": "Description 0",
    }
    assert result.metadata["provider"] == "brave"


def test_search_empty_results():
    tool = WebSearch(transport=httpx.MockTransport(_json_handler(0)))
    result = run_async(tool.execute({"query": "python asyncio"}))
    assert result.success is True
    assert result.output["count"] == 0
    assert result.output["results"] == []


# ---------------------------------------------------------------------------
# web.search — failure paths
# ---------------------------------------------------------------------------

def test_missing_api_key(monkeypatch):
    monkeypatch.setattr(settings, "brave_api_key", "")
    tool = WebSearch()
    result = run_async(tool.execute({"query": "python asyncio"}))
    assert result.success is False
    assert "BRAVE_API_KEY" in result.error


def test_rate_limited():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="rate limited")

    tool = WebSearch(transport=httpx.MockTransport(handler))
    result = run_async(tool.execute({"query": "python asyncio"}))
    assert result.success is False
    assert "429" in result.error


def test_unauthorized():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="unauthorized")

    tool = WebSearch(transport=httpx.MockTransport(handler))
    result = run_async(tool.execute({"query": "python asyncio"}))
    assert result.success is False
    assert result.error


def test_server_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    tool = WebSearch(transport=httpx.MockTransport(handler))
    result = run_async(tool.execute({"query": "python asyncio"}))
    assert result.success is False
    assert "500" in result.error


def test_upstream_timeout():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("boom")

    tool = WebSearch(transport=httpx.MockTransport(handler))
    result = run_async(tool.execute({"query": "python asyncio"}))
    assert result.success is False
    assert result.error