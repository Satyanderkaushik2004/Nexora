"""Local provider backed by an Ollama server. Requires no API key."""

from __future__ import annotations

import requests

from clients.base import (
    BaseClient,
    ProviderResponseError,
    ProviderUnavailableError,
    raise_for_status,
)


class LocalClient(BaseClient):
    name = "local"
    display_name = "Local (Ollama)"

    def __init__(self, base_url: str, model: str, timeout: int):
        super().__init__(model)
        self._base_url = base_url
        self._timeout = timeout

    @property
    def configured(self) -> bool:
        # No credential is needed. Whether the server is actually up is
        # discovered at call time and tracked by the scoring engine.
        return True

    def ask(self, query: str) -> str:
        try:
            response = requests.post(
                f"{self._base_url}/api/generate",
                json={"model": self.model, "prompt": query, "stream": False},
                timeout=self._timeout,
            )
        except requests.Timeout:
            raise ProviderUnavailableError("The local model server timed out.") from None
        except requests.RequestException:
            raise ProviderUnavailableError("The local model server could not be reached.") from None

        raise_for_status(response.status_code)
        try:
            text = response.json().get("response")
        except (ValueError, AttributeError):
            raise ProviderResponseError("The local model returned an invalid response.") from None
        if not isinstance(text, str) or not text.strip():
            raise ProviderResponseError("The local model returned an empty response.")
        return text
