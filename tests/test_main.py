import pytest

import main
from core.config import load_settings


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch):
    """Never read a developer's local .env during tests."""
    monkeypatch.setattr(main, "load_settings", lambda: load_settings(load_env_file=False))


def test_debug_on_public_host_is_refused(monkeypatch):
    monkeypatch.setenv("NEXORA_DEBUG", "true")
    monkeypatch.setenv("NEXORA_HOST", "0.0.0.0")
    with pytest.raises(SystemExit) as info:
        main.main()
    assert "Refusing to start" in str(info.value)


def test_default_run_has_debug_disabled(monkeypatch):
    captured = {}

    class DummyApp:
        def run(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(main, "create_app", lambda settings: DummyApp())
    main.main()
    assert captured["debug"] is False and captured["host"] == "127.0.0.1"
