"""Shared provider-client primitives.

Provider errors carry only fixed, user-safe messages. Upstream response bodies,
headers, and exception text are deliberately never attached to them, because
they can echo credentials or internal details.
"""

from __future__ import annotations

import requests


class ProviderError(Exception):
    """Base class for all provider failures. ``kind`` is a stable category."""

    kind = "upstream_error"

    def __init__(self, message: str = "The AI provider returned an error.", status: int | None = None):
        super().__init__(message)
        self.status = status


class ProviderUnavailableError(ProviderError):
    """Provider unreachable, timed out, or not configured."""

    kind = "unavailable"


class ProviderAuthError(ProviderError):
    """Provider rejected the configured credentials."""

    kind = "auth"


class ProviderRateLimitError(ProviderError):
    """Provider rate limit or quota reached."""

    kind = "rate_limited"


class ProviderResponseError(ProviderError):
    """Provider replied, but not with a usable completion."""

    kind = "bad_response"


def raise_for_status(status: int) -> None:
    """Translate an upstream HTTP status into a sanitized ProviderError."""
    if status == 200:
        return
    if status in (401, 403):
        raise ProviderAuthError("The provider rejected the configured credentials.", status)
    if status == 429:
        raise ProviderRateLimitError("The provider rate limit was reached.", status)
    if status == 404:
        raise ProviderResponseError("The requested model or endpoint was not found.", status)
    raise ProviderError(f"The provider returned HTTP {status}.", status)


def extract_chat_content(data: object) -> str:
    """Return ``choices[0].message.content`` or raise ProviderResponseError."""
    try:
        content = data["choices"][0]["message"]["content"]  # type: ignore[index]
    except (KeyError, IndexError, TypeError):
        raise ProviderResponseError("The provider returned an unexpected response format.") from None
    if not isinstance(content, str) or not content.strip():
        raise ProviderResponseError("The provider returned an empty response.")
    return content


class BaseClient:
    """Interface every provider client implements."""

    name = ""
    display_name = ""

    def __init__(self, model: str):
        self.model = model

    @property
    def configured(self) -> bool:
        raise NotImplementedError

    def ask(self, query: str) -> str:
        raise NotImplementedError


class OpenAICompatibleClient(BaseClient):
    """Client for providers exposing an OpenAI-style /chat/completions API."""

    url = ""
    system_prompt = "You are a helpful assistant."

    def __init__(self, api_key: str, model: str, timeout: int):
        super().__init__(model)
        self._api_key = api_key
        self._timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self._api_key)

    def ask(self, query: str) -> str:
        if not self.configured:
            raise ProviderUnavailableError(f"{self.display_name} is not configured.")

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": query},
            ],
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        try:
            response = requests.post(self.url, headers=headers, json=payload, timeout=self._timeout)
        except requests.Timeout:
            raise ProviderUnavailableError(f"{self.display_name} timed out.") from None
        except requests.RequestException:
            raise ProviderUnavailableError(f"{self.display_name} could not be reached.") from None

        raise_for_status(response.status_code)
        try:
            data = response.json()
        except ValueError:
            raise ProviderResponseError("The provider returned invalid JSON.") from None
        return extract_chat_content(data)
