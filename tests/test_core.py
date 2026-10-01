import pytest

from clients.base import (ProviderAuthError, ProviderRateLimitError,
                          ProviderUnavailableError)
from core.config import ConfigError, load_settings
from core.failover import AllProvidersFailedError, execute_with_failover
from core.registry import ProviderRegistry
from core.request_analyzer import analyze
from core.router import NoProviderAvailableError, Router
from core.scoring_engine import ScoringEngine
from tests.conftest import FakeClient
from utils.logger import redact, register_secret


# ---------- analyzer ----------
@pytest.mark.parametrize("text,expected", [
    ("write a python function", "coding"),
    ("Help me debug this", "coding"),
    ("what is the latest news on X", "research"),
    ("tell me a joke", "general"),
    ("how do I decode this?", "general"),   # whole-word matching
    ("", "general"),
])
def test_analyzer(text, expected):
    assert analyze(text) == expected


# ---------- scoring ----------
def test_new_provider_has_finite_neutral_score():
    engine = ScoringEngine(["a"])
    assert 0.0 <= engine.score("a") <= 1.0


def test_failures_lower_score_without_crashing():
    engine = ScoringEngine(["a", "b"])
    for _ in range(10):
        engine.record_failure("a")
    engine.record_success("b", 0.5)
    assert engine.score("a") < engine.score("b")
    assert engine.score("a") > 0  # never collapses to exactly zero


def test_zero_latency_and_unknown_provider_do_not_divide_by_zero():
    engine = ScoringEngine(["a"])
    engine.record_success("a", 0.0)
    assert engine.score("a") <= 1.0
    assert 0.0 <= engine.score("never-seen") <= 1.0


def test_cooldown_after_consecutive_failures_then_expires():
    now = [100.0]
    engine = ScoringEngine(["a"], cooldown_failures=3, cooldown_seconds=60, clock=lambda: now[0])
    for _ in range(3):
        engine.record_failure("a")
    assert engine.is_cooling_down("a")
    now[0] += 61
    assert not engine.is_cooling_down("a")


def test_success_resets_consecutive_failures():
    engine = ScoringEngine(["a"], cooldown_failures=2)
    engine.record_failure("a")
    engine.record_success("a", 1.0)
    engine.record_failure("a")
    assert not engine.is_cooling_down("a")


# ---------- router ----------
def make_router(clients, settings):
    registry = ProviderRegistry(clients)
    scoring = ScoringEngine(registry.names())
    return Router(registry, scoring, settings.routing), registry, scoring


def test_router_follows_task_preferences(settings, four_clients):
    router, _, _ = make_router(four_clients, settings)
    assert router.rank("coding")[0] == "deepseek"
    assert router.rank("research")[0] == "perplexity"
    assert router.rank("general")[0] == "local"


def test_router_never_selects_unconfigured_provider(settings):
    clients = [FakeClient("deepseek", configured=False), FakeClient("openai"), FakeClient("local")]
    router, _, _ = make_router(clients, settings)
    assert "deepseek" not in router.rank("coding")


def test_router_raises_when_nothing_configured(settings):
    router, _, _ = make_router([FakeClient("openai", configured=False)], settings)
    with pytest.raises(NoProviderAvailableError):
        router.rank("general")


def test_router_is_performance_aware(settings, four_clients):
    router, _, scoring = make_router(four_clients, settings)
    for _ in range(3):
        scoring.record_failure("deepseek")
    for _ in range(30):
        scoring.record_success("openai", 0.2)
    # deepseek is the coding favourite but is cooling down -> openai leads
    assert router.rank("coding")[0] == "openai"


def test_router_uses_cooling_providers_when_nothing_else(settings):
    router, _, scoring = make_router([FakeClient("openai")], settings)
    for _ in range(5):
        scoring.record_failure("openai")
    assert router.rank("general") == ["openai"]


def test_manual_choice_first_then_fallbacks(settings, four_clients):
    router, _, _ = make_router(four_clients, settings)
    plan = router.plan("general", "openai")
    assert plan[0] == "openai" and len(plan) == 4 and len(set(plan)) == 4


def test_manual_choice_unconfigured_raises(settings):
    router, _, _ = make_router([FakeClient("openai", configured=False), FakeClient("local")], settings)
    with pytest.raises(NoProviderAvailableError):
        router.plan("general", "openai")


# ---------- failover ----------
def run_failover(clients, plan, max_attempts=3):
    registry = ProviderRegistry(clients)
    scoring = ScoringEngine(registry.names())
    return execute_with_failover(plan, registry, scoring, "hello", max_attempts), scoring


def failing(exc):
    def _raise(_):
        raise exc
    return _raise


def test_failover_uses_backup_on_primary_failure():
    clients = [FakeClient("a", behavior=failing(ProviderUnavailableError("x"))), FakeClient("b")]
    result, scoring = run_failover(clients, ["a", "b"])
    assert result.provider == "b" and result.fallback_used
    assert scoring.snapshot()["a"]["failures"] == 1


def test_failover_no_fallback_when_primary_succeeds():
    clients = [FakeClient("a"), FakeClient("b")]
    result, _ = run_failover(clients, ["a", "b"])
    assert result.provider == "a" and not result.fallback_used
    assert clients[1].calls == 0


def test_failover_all_fail_raises_with_kinds():
    clients = [FakeClient("a", behavior=failing(ProviderRateLimitError())),
               FakeClient("b", behavior=failing(ProviderAuthError()))]
    with pytest.raises(AllProvidersFailedError) as info:
        run_failover(clients, ["a", "b"])
    assert info.value.error_kinds == {"rate_limited", "auth"}


def test_failover_survives_unexpected_client_exception():
    clients = [FakeClient("a", behavior=failing(RuntimeError("boom"))), FakeClient("b")]
    result, _ = run_failover(clients, ["a", "b"])
    assert result.provider == "b"


def test_failover_respects_max_attempts():
    clients = [FakeClient("a", behavior=failing(ProviderUnavailableError())), FakeClient("b")]
    with pytest.raises(AllProvidersFailedError):
        run_failover(clients, ["a", "b"], max_attempts=1)
    assert clients[1].calls == 0


# ---------- config / logging ----------
def test_defaults_are_safe(settings):
    assert settings.debug is False
    assert settings.host == "127.0.0.1"
    assert settings.ollama_base_url == "http://localhost:11434"


def test_secrets_not_in_repr(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-real-key-123456")
    assert "sk-test" not in repr(load_settings(load_env_file=False))


def test_invalid_config_fails_fast(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    with pytest.raises(ConfigError):
        load_settings(bad, load_env_file=False)


def test_redaction():
    register_secret("custom-secret-value-xyz")
    out = redact("Authorization: Bearer abcdef123456 key sk-abcdefgh12345678 custom-secret-value-xyz")
    assert "abcdef123456" not in out and "sk-abcdefgh" not in out and "custom-secret" not in out
