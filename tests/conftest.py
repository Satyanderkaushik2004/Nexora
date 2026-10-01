import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.server import create_app  # noqa: E402
from clients.base import BaseClient  # noqa: E402
from core.config import load_settings  # noqa: E402
from core.registry import ProviderRegistry  # noqa: E402

ENV_VARS = [
    "OPENAI_API_KEY", "DEEPSEEK_API_KEY", "PERPLEXITY_API_KEY", "NEXORA_DEBUG",
    "NEXORA_HOST", "NEXORA_PORT", "OLLAMA_BASE_URL", "OLLAMA_MODEL", "NEXORA_CONFIG",
    "NEXORA_MAX_QUERY_CHARS", "NEXORA_REQUEST_TIMEOUT",
]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for var in ENV_VARS:
        monkeypatch.delenv(var, raising=False)


class FakeClient(BaseClient):
    """Scriptable provider for tests. ``behavior`` is a callable or a string."""

    def __init__(self, name, configured=True, behavior="ok"):
        super().__init__(model=f"{name}-model")
        self.name = name
        self.display_name = name.title()
        self._configured = configured
        self.behavior = behavior
        self.calls = 0

    @property
    def configured(self):
        return self._configured

    def ask(self, query):
        self.calls += 1
        if callable(self.behavior):
            return self.behavior(query)
        return f"{self.name} says hi" if self.behavior == "ok" else self.behavior


@pytest.fixture
def settings():
    return load_settings(load_env_file=False)


@pytest.fixture
def make_app(settings):
    def _make(clients):
        registry = ProviderRegistry(clients)
        app = create_app(settings, registry=registry)
        app.config["TESTING"] = True
        return app, registry
    return _make


@pytest.fixture
def four_clients():
    return [FakeClient("openai"), FakeClient("deepseek"), FakeClient("perplexity"), FakeClient("local")]
