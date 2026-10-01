"""Provider registry: the single place providers are defined and looked up."""

from __future__ import annotations

from typing import Iterable

from clients.base import BaseClient
from clients.deepseek_client import DeepSeekClient
from clients.local_client import LocalClient
from clients.openai_client import OpenAIClient
from clients.perplexity_client import PerplexityClient
from core.config import Settings
from utils.logger import register_secret


class ProviderRegistry:
    def __init__(self, clients: Iterable[BaseClient]):
        self._clients = {client.name: client for client in clients}

    def names(self) -> list[str]:
        return list(self._clients)

    def is_known(self, name: str) -> bool:
        return name in self._clients

    def get(self, name: str) -> BaseClient:
        return self._clients[name]

    def is_available(self, name: str) -> bool:
        client = self._clients.get(name)
        return client is not None and client.configured

    def available_names(self) -> list[str]:
        return [name for name in self._clients if self._clients[name].configured]

    def describe(self) -> list[dict[str, object]]:
        """Public, secret-free provider summary."""
        return [
            {
                "name": client.name,
                "display_name": client.display_name,
                "model": client.model,
                "available": client.configured,
            }
            for client in self._clients.values()
        ]


def build_registry(settings: Settings) -> ProviderRegistry:
    for key in (settings.openai_api_key, settings.deepseek_api_key, settings.perplexity_api_key):
        register_secret(key)

    return ProviderRegistry(
        [
            OpenAIClient(settings.openai_api_key, settings.openai_model, settings.request_timeout),
            DeepSeekClient(settings.deepseek_api_key, settings.deepseek_model, settings.request_timeout),
            PerplexityClient(settings.perplexity_api_key, settings.perplexity_model, settings.request_timeout),
            LocalClient(settings.ollama_base_url, settings.ollama_model, settings.ollama_timeout),
        ]
    )
