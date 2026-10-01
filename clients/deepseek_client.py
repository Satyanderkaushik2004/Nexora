"""DeepSeek provider (OpenAI-compatible HTTP API)."""

from clients.base import OpenAICompatibleClient


class DeepSeekClient(OpenAICompatibleClient):
    name = "deepseek"
    display_name = "DeepSeek"
    url = "https://api.deepseek.com/v1/chat/completions"
    system_prompt = "You are a helpful AI assistant."
