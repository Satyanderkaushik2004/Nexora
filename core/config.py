"""Configuration loading for NEXORA AI Router.

Secrets and deployment settings come from environment variables (optionally
loaded from a local, git-ignored ``.env`` file). Non-secret routing behaviour
comes from ``configs/config.json``.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = ROOT_DIR / "configs" / "config.json"

TASK_TYPES = ("coding", "research", "general")
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


class ConfigError(Exception):
    """Raised at startup when configuration is invalid."""


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer") from exc
    if value < minimum:
        raise ConfigError(f"{name} must be >= {minimum}")
    return value


def _env_str(name: str, default: str = "") -> str:
    value = os.getenv(name)
    return value.strip() if value and value.strip() else default


@dataclass(frozen=True)
class RoutingConfig:
    task_preferences: dict[str, list[str]]
    preference_weight: float
    performance_weight: float
    max_attempts: int
    success_weight: float
    latency_weight: float
    cooldown_failures: int
    cooldown_seconds: float


@dataclass(frozen=True)
class Settings:
    debug: bool
    host: str
    port: int
    log_level: str
    max_query_chars: int
    max_title_chars: int
    request_timeout: int
    ollama_timeout: int
    ollama_base_url: str
    ollama_model: str
    openai_model: str
    deepseek_model: str
    perplexity_model: str
    routing: RoutingConfig
    # Secrets: excluded from repr so they cannot leak through logging/debugging.
    openai_api_key: str = field(default="", repr=False)
    deepseek_api_key: str = field(default="", repr=False)
    perplexity_api_key: str = field(default="", repr=False)


def _load_routing(path: Path) -> RoutingConfig:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"Config file not found: {path.name}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Config file {path.name} is not valid JSON") from exc

    routing = raw.get("routing", {})
    scoring = raw.get("scoring", {})
    failover = raw.get("failover", {})

    prefs = routing.get("task_preferences", {})
    if not isinstance(prefs, dict):
        raise ConfigError("routing.task_preferences must be an object")
    clean_prefs: dict[str, list[str]] = {}
    for task in TASK_TYPES:
        names = prefs.get(task, [])
        if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
            raise ConfigError(f"routing.task_preferences.{task} must be a list of provider names")
        clean_prefs[task] = [n.strip().lower() for n in names]

    def number(section: dict, key: str, default: float) -> float:
        value = section.get(key, default)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            raise ConfigError(f"{key} must be a non-negative number")
        return float(value)

    return RoutingConfig(
        task_preferences=clean_prefs,
        preference_weight=number(routing, "preference_weight", 0.6),
        performance_weight=number(routing, "performance_weight", 0.4),
        max_attempts=max(1, int(number(failover, "max_attempts", 3))),
        success_weight=number(scoring, "success_weight", 0.7),
        latency_weight=number(scoring, "latency_weight", 0.3),
        cooldown_failures=max(1, int(number(scoring, "cooldown_after_consecutive_failures", 3))),
        cooldown_seconds=number(scoring, "cooldown_seconds", 60),
    )


def load_settings(config_path: str | Path | None = None, load_env_file: bool = True) -> Settings:
    if load_env_file:
        load_dotenv(ROOT_DIR / ".env")

    path = Path(config_path or _env_str("NEXORA_CONFIG") or DEFAULT_CONFIG_PATH)
    default_timeout = _env_int("NEXORA_REQUEST_TIMEOUT", 60)

    return Settings(
        debug=_env_bool("NEXORA_DEBUG", False),
        host=_env_str("NEXORA_HOST", "127.0.0.1"),
        port=_env_int("NEXORA_PORT", 5000),
        log_level=_env_str("NEXORA_LOG_LEVEL", "INFO").upper(),
        max_query_chars=_env_int("NEXORA_MAX_QUERY_CHARS", 8000),
        max_title_chars=_env_int("NEXORA_MAX_TITLE_INPUT_CHARS", 2000),
        request_timeout=default_timeout,
        ollama_timeout=_env_int("OLLAMA_TIMEOUT", max(default_timeout, 120)),
        ollama_base_url=_env_str("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/"),
        ollama_model=_env_str("OLLAMA_MODEL", "llama3"),
        openai_model=_env_str("OPENAI_MODEL", "gpt-4o-mini"),
        deepseek_model=_env_str("DEEPSEEK_MODEL", "deepseek-chat"),
        perplexity_model=_env_str("PERPLEXITY_MODEL", "sonar"),
        routing=_load_routing(path),
        openai_api_key=_env_str("OPENAI_API_KEY"),
        deepseek_api_key=_env_str("DEEPSEEK_API_KEY"),
        perplexity_api_key=_env_str("PERPLEXITY_API_KEY"),
    )
