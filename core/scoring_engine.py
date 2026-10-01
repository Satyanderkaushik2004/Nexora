"""Thread-safe, in-memory provider performance tracking and scoring.

Statistics reset when the process restarts. Scores are always finite and lie in
[0, 1]; a provider with no history gets a neutral score rather than an error.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable, Iterable

NEUTRAL_LATENCY_SCORE = 0.5


@dataclass
class ProviderStats:
    successes: int = 0
    failures: int = 0
    total_latency: float = 0.0
    consecutive_failures: int = 0
    last_failure_at: float | None = None


class ScoringEngine:
    def __init__(
        self,
        providers: Iterable[str],
        success_weight: float = 0.7,
        latency_weight: float = 0.3,
        cooldown_failures: int = 3,
        cooldown_seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._stats = {name: ProviderStats() for name in providers}
        self._success_weight = success_weight
        self._latency_weight = latency_weight
        self._cooldown_failures = cooldown_failures
        self._cooldown_seconds = cooldown_seconds
        self._clock = clock
        self._lock = threading.Lock()

    def _get(self, name: str) -> ProviderStats:
        return self._stats.setdefault(name, ProviderStats())

    def record_success(self, name: str, latency_seconds: float) -> None:
        with self._lock:
            stats = self._get(name)
            stats.successes += 1
            stats.total_latency += max(0.0, latency_seconds)
            stats.consecutive_failures = 0

    def record_failure(self, name: str) -> None:
        with self._lock:
            stats = self._get(name)
            stats.failures += 1
            stats.consecutive_failures += 1
            stats.last_failure_at = self._clock()

    def score(self, name: str) -> float:
        """Blend of smoothed success rate and latency, in [0, 1].

        * Success rate uses Laplace smoothing, so an untested provider scores
          0.5 and a single failure cannot collapse the score to zero.
        * Latency score is ``1 / (1 + average_seconds)``; providers that have
          never succeeded get a neutral latency score instead of dividing by 0.
        """
        with self._lock:
            stats = self._get(name)
            calls = stats.successes + stats.failures
            success_rate = (stats.successes + 1) / (calls + 2)
            if stats.successes:
                latency_score = 1.0 / (1.0 + stats.total_latency / stats.successes)
            else:
                latency_score = NEUTRAL_LATENCY_SCORE

        total_weight = self._success_weight + self._latency_weight
        if total_weight <= 0:
            return success_rate
        blended = (self._success_weight * success_rate + self._latency_weight * latency_score) / total_weight
        return min(1.0, max(0.0, blended))

    def is_cooling_down(self, name: str) -> bool:
        """True after repeated consecutive failures, until the cooldown elapses."""
        with self._lock:
            stats = self._get(name)
            if stats.consecutive_failures < self._cooldown_failures or stats.last_failure_at is None:
                return False
            return (self._clock() - stats.last_failure_at) < self._cooldown_seconds

    def snapshot(self) -> dict[str, dict[str, float | int]]:
        with self._lock:
            return {
                name: {
                    "successes": s.successes,
                    "failures": s.failures,
                    "consecutive_failures": s.consecutive_failures,
                }
                for name, s in self._stats.items()
            }
