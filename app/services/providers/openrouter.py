from __future__ import annotations

import json
from typing import Any

import httpx

from app.config.settings import config, settings
from app.services.model_provider import (
    ModelProvider,
    ModelResponse,
    ProviderError,
    ProviderNotConfiguredError,
)


class OpenRouterProvider(ModelProvider):
    name = "openrouter"

    def __init__(self) -> None:
        self.base_url = config.providers.get("openrouter", self._default_cfg()).base_url.rstrip("/")
        self.model = config.providers.get("openrouter", self._default_cfg()).model
        self._api_key = settings.openrouter_api_key

    @staticmethod
    def _default_cfg():
        from app.config.settings import ProviderConfig

        return ProviderConfig(
            model="meta-llama/llama-3.3-70b-instruct:free",
            base_url="https://openrouter.ai/api/v1",
            supports_tools=True,
        )

    async def generate(self, prompt: str, tools: list[dict] | None = None) -> ModelResponse:
        if not self._api_key:
            raise ProviderNotConfiguredError(
                "OpenRouter API key is not set. Add OPENROUTER_API_KEY to the environment or .env."
            )
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
        }
        if tools:
            payload["tools"] = tools
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(base_url=self.base_url, timeout=60.0) as client:
                response = await client.post("/chat/completions", json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            raise ProviderError(f"OpenRouter request failed: {exc}") from exc
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        return ModelResponse(
            content=content or "",
            model=data.get("model", self.model),
            provider=self.name,
            raw={"usage": data.get("usage", {})},
        )

    async def check_availability(self) -> bool:
        if not self._api_key:
            return False
        headers = {"Authorization": f"Bearer {self._api_key}"}
        try:
            async with httpx.AsyncClient(base_url=self.base_url, timeout=10.0) as client:
                response = await client.get("/models", headers=headers)
                return response.status_code == 200
        except httpx.HTTPError:
            return False

    def get_model_info(self) -> dict[str, Any]:
        cfg = config.providers.get("openrouter", self._default_cfg())
        return {
            "provider": self.name,
            "model": self.model,
            "base_url": self.base_url,
            "supports_tools": cfg.supports_tools,
            "price_desc": cfg.price_desc,
            "data_handling": cfg.data_handling,
            "configured": bool(self._api_key),
        }