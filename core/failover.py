"""Failover execution: try providers in order until one succeeds."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from clients.base import ProviderError
from core.registry import ProviderRegistry
from core.scoring_engine import ScoringEngine
from utils.logger import log_event


@dataclass
class Attempt:
    provider: str
    ok: bool
    error_kind: str | None = None
    latency_ms: int = 0


@dataclass
class FailoverResult:
    text: str
    provider: str
    attempts: list[Attempt] = field(default_factory=list)

    @property
    def fallback_used(self) -> bool:
        return len(self.attempts) > 1


class AllProvidersFailedError(Exception):
    def __init__(self, attempts: list[Attempt]):
        super().__init__("All attempted providers failed.")
        self.attempts = attempts

    @property
    def error_kinds(self) -> set[str]:
        return {a.error_kind or "upstream_error" for a in self.attempts}


def execute_with_failover(
    plan: list[str],
    registry: ProviderRegistry,
    scoring: ScoringEngine,
    query: str,
    max_attempts: int,
) -> FailoverResult:
    attempts: list[Attempt] = []

    for name in plan[: max(1, max_attempts)]:
        client = registry.get(name)
        started = time.perf_counter()
        try:
            text = client.ask(query)
        except ProviderError as exc:
            elapsed = time.perf_counter() - started
            scoring.record_failure(name)
            attempts.append(Attempt(name, False, exc.kind, int(elapsed * 1000)))
            log_event("provider_failed", logging.WARNING, provider=name, kind=exc.kind, status=exc.status)
            continue
        except Exception as exc:  # defensive: a client bug must not break failover
            elapsed = time.perf_counter() - started
            scoring.record_failure(name)
            attempts.append(Attempt(name, False, "internal_error", int(elapsed * 1000)))
            log_event("provider_failed", logging.ERROR, provider=name, kind="internal_error",
                      error_type=type(exc).__name__)
            continue

        elapsed = time.perf_counter() - started
        scoring.record_success(name, elapsed)
        attempts.append(Attempt(name, True, None, int(elapsed * 1000)))
        log_event("provider_succeeded", provider=name, latency_s=f"{elapsed:.2f}")
        return FailoverResult(text=text, provider=name, attempts=attempts)

    raise AllProvidersFailedError(attempts)
