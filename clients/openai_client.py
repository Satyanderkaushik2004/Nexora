"""OpenAI provider (official SDK)."""

from __future__ import annotations

import openai
from openai import OpenAI

from clients.base import (
    BaseClient,
    ProviderAuthError,
    ProviderError,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderUnavailableError,
)


class OpenAIClient(BaseClient):
    name = "openai"
    display_name = "OpenAI"

    def __init__(self, api_key: str, model: str, timeout: int):
        super().__init__(model)
        self._client = OpenAI(api_key=api_key, timeout=timeout, max_retries=0) if api_key else None

    @property
    def configured(self) -> bool:
        return self._client is not None

    def ask(self, query: str) -> str:
        if self._client is None:
            raise ProviderUnavailableError("OpenAI is not configured.")
        try:
            response = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": query},
                ],
            )
        except (openai.AuthenticationError, openai.PermissionDeniedError):
            raise ProviderAuthError("The provider rejected the configured credentials.", 401) from None
        except openai.RateLimitError:
            raise ProviderRateLimitError("The provider rate limit was reached.", 429) from None
        except openai.APIConnectionError:  # includes timeouts
            raise ProviderUnavailableError("OpenAI could not be reached.") from None
        except openai.APIStatusError as exc:
            raise ProviderError(f"The provider returned HTTP {exc.status_code}.", exc.status_code) from None

        try:
            content = response.choices[0].message.content
        except (AttributeError, IndexError):
            raise ProviderResponseError("The provider returned an unexpected response format.") from None
        if not isinstance(content, str) or not content.strip():
            raise ProviderResponseError("The provider returned an empty response.")
        return content
