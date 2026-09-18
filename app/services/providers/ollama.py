from __future__ import annotations

from typing import Any

import httpx

from app.config.settings import config, settings
from app.services.model_provider import (
    ModelProvider,
    ModelResponse,
    ProviderError,
)


class OllamaProvider(ModelProvider):
    name = "ollama"

    def __init__(self) -> None:
        self.base_url = settings.ollama_base_url.rstrip("/")
        self.model = config.providers.get("ollama", self._default_cfg()).model

    @staticmethod
    def _default_cfg():
        from app.config.settings import ProviderConfig

        return ProviderConfig(
            model="llama3.2",
            base_url="http://localhost:11434",
            supports_tools=True,
            price_desc="local-free",
            data_handling="local-only",
        )

    async def generate(self, prompt: str, tools: list[dict] | None = None) -> ModelResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
        }
        if tools:
            payload["tools"] = tools
        try:
            async with httpx.AsyncClient(base_url=self.base_url, timeout=120.0) as client:
                response = await client.post("/api/chat", json=payload)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            raise ProviderError(f"Ollama request failed (is {self.base_url} running?): {exc}") from exc
        content = data.get("message", {}).get("content", "")
        return ModelResponse(content=content or "", model=self.model, provider=self.name)

    async def check_availability(self) -> bool:
        try:
            async with httpx.AsyncClient(base_url=self.base_url, timeout=2.0) as client:
                response = await client.get("/api/tags")
                return response.status_code == 200
        except httpx.HTTPError:
            return False

    def get_model_info(self) -> dict[str, Any]:
        cfg = config.providers.get("ollama", self._default_cfg())
        return {
            "provider": self.name,
            "model": self.model,
            "base_url": self.base_url,
            "supports_tools": cfg.supports_tools,
            "price_desc": cfg.price_desc,
            "data_handling": cfg.data_handling,
            "configured": True,
        }