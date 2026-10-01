"""Perplexity provider (OpenAI-compatible HTTP API with web-grounded answers)."""

from clients.base import OpenAICompatibleClient


class PerplexityClient(OpenAICompatibleClient):
    name = "perplexity"
    display_name = "Perplexity"
    url = "https://api.perplexity.ai/chat/completions"
    system_prompt = "Be precise and factual."
