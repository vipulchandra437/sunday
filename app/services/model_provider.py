from __future__ import annotations

import abc
from typing import Any

from pydantic import BaseModel, Field

from app.config.settings import config


class ModelResponse(BaseModel):
    content: str = ""
    model: str = ""
    provider: str = ""
    raw: dict[str, Any] = Field(default_factory=dict)


class ProviderError(RuntimeError):
    pass


class ProviderNotConfiguredError(ProviderError):
    pass


class ModelProvider(abc.ABC):
    name: str = "base"
    model: str = ""

    @abc.abstractmethod
    async def generate(self, prompt: str, tools: list[dict] | None = None) -> ModelResponse:
        raise NotImplementedError

    @abc.abstractmethod
    async def check_availability(self) -> bool:
        raise NotImplementedError

    @abc.abstractmethod
    def get_model_info(self) -> dict[str, Any]:
        raise NotImplementedError


def get_provider(name: str) -> ModelProvider:
    if name == "openrouter":
        from app.services.providers.openrouter import OpenRouterProvider

        return OpenRouterProvider()
    if name == "ollama":
        from app.services.providers.ollama import OllamaProvider

        return OllamaProvider()
    raise ValueError(f"unknown model provider: {name}")


def default_provider() -> ModelProvider:
    return get_provider(config.default_model_provider)


def provider_status() -> dict[str, dict[str, Any]]:
    statuses: dict[str, dict[str, Any]] = {}
    for name in ["openrouter", "ollama"]:
        try:
            provider = get_provider(name)
            statuses[name] = {
                "model": provider.model,
                "info": provider.get_model_info(),
                "availability": "unknown",
            }
        except ValueError:
            statuses[name] = {"error": f"provider {name} not available"}
    return statuses