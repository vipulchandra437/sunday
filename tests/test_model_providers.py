import asyncio

import pytest

from app.services.model_provider import ProviderNotConfiguredError, get_provider
from app.services.providers.ollama import OllamaProvider
from app.services.providers.openrouter import OpenRouterProvider


def test_factory_returns_providers():
    assert isinstance(get_provider("openrouter"), OpenRouterProvider)
    assert isinstance(get_provider("ollama"), OllamaProvider)


def test_factory_unknown_provider_raises():
    with pytest.raises(ValueError):
        get_provider("does-not-exist")


def test_openrouter_model_info_without_key():
    provider = OpenRouterProvider()
    info = provider.get_model_info()
    assert info["provider"] == "openrouter"
    assert info["configured"] is False
    assert isinstance(info["model"], str)


def test_ollama_model_info():
    info = OllamaProvider().get_model_info()
    assert info["provider"] == "ollama"
    assert info["data_handling"] == "local-only"


def test_openrouter_availability_false_without_key():
    provider = OpenRouterProvider()
    assert asyncio.run(provider.check_availability()) is False


def test_openrouter_generate_requires_key():
    provider = OpenRouterProvider()
    with pytest.raises(ProviderNotConfiguredError):
        asyncio.run(provider.generate("hello"))


def test_ollama_availability_false_when_server_down():
    provider = OllamaProvider()
    assert asyncio.run(provider.check_availability()) is False