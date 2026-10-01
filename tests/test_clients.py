import pytest
import requests

from clients.base import (ProviderAuthError, ProviderRateLimitError,
                          ProviderResponseError, ProviderUnavailableError)
from clients.deepseek_client import DeepSeekClient
from clients.local_client import LocalClient
from clients.openai_client import OpenAIClient

SECRET = "sk-test-not-a-real-key-123456"


class FakeResponse:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def patch_post(monkeypatch, response=None, exc=None):
    def fake_post(*args, **kwargs):
        if exc:
            raise exc
        return response
    monkeypatch.setattr(requests, "post", fake_post)


def test_unconfigured_clients_report_unavailable():
    assert not DeepSeekClient("", "m", 5).configured
    assert not OpenAIClient("", "m", 5).configured
    with pytest.raises(ProviderUnavailableError):
        DeepSeekClient("", "m", 5).ask("hi")
    with pytest.raises(ProviderUnavailableError):
        OpenAIClient("", "m", 5).ask("hi")


def test_deepseek_success(monkeypatch):
    patch_post(monkeypatch, FakeResponse(200, {"choices": [{"message": {"content": "hello"}}]}))
    assert DeepSeekClient(SECRET, "m", 5).ask("hi") == "hello"


@pytest.mark.parametrize("status,exc_type", [(401, ProviderAuthError), (403, ProviderAuthError),
                                             (429, ProviderRateLimitError)])
def test_status_mapping_never_leaks_key(monkeypatch, status, exc_type):
    patch_post(monkeypatch, FakeResponse(status, {"error": f"bad key {SECRET}"}))
    with pytest.raises(exc_type) as info:
        DeepSeekClient(SECRET, "m", 5).ask("hi")
    assert SECRET not in str(info.value)


def test_malformed_and_empty_responses(monkeypatch):
    for payload in ({}, {"choices": []}, {"choices": [{"message": {"content": "  "}}]}):
        patch_post(monkeypatch, FakeResponse(200, payload))
        with pytest.raises(ProviderResponseError):
            DeepSeekClient(SECRET, "m", 5).ask("hi")
    patch_post(monkeypatch, FakeResponse(200, None))
    with pytest.raises(ProviderResponseError):
        DeepSeekClient(SECRET, "m", 5).ask("hi")


def test_network_errors_are_sanitized(monkeypatch):
    patch_post(monkeypatch, exc=requests.ConnectionError(f"failed with {SECRET}"))
    with pytest.raises(ProviderUnavailableError) as info:
        DeepSeekClient(SECRET, "m", 5).ask("hi")
    assert SECRET not in str(info.value)
    patch_post(monkeypatch, exc=requests.Timeout())
    with pytest.raises(ProviderUnavailableError):
        DeepSeekClient(SECRET, "m", 5).ask("hi")


def test_local_success_and_server_down(monkeypatch):
    local = LocalClient("http://localhost:11434", "llama3", 5)
    assert local.configured  # no key required
    patch_post(monkeypatch, FakeResponse(200, {"response": "local hi"}))
    assert local.ask("hi") == "local hi"
    patch_post(monkeypatch, exc=requests.ConnectionError("refused"))
    with pytest.raises(ProviderUnavailableError):
        local.ask("hi")


def test_local_missing_model_is_clean_error(monkeypatch):
    patch_post(monkeypatch, FakeResponse(404, {"error": "model not found"}))
    with pytest.raises(ProviderResponseError):
        LocalClient("http://localhost:11434", "nope", 5).ask("hi")
