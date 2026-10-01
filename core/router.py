"""The single authoritative routing implementation.

Routing combines two signals for every *available* provider:

  1. Task preference -- an ordered list per task type from ``configs/config.json``.
  2. Observed performance -- the scoring engine's success/latency score.

``final = preference_weight * preference_score + performance_weight * performance_score``

Providers that are not configured are never selected. Providers in a failure
cooldown are skipped unless nothing else is available.
"""

from __future__ import annotations

from core.config import RoutingConfig
from core.registry import ProviderRegistry
from core.scoring_engine import ScoringEngine

UNLISTED_PREFERENCE = 0.0


class NoProviderAvailableError(Exception):
    """No configured provider can serve the request."""


class Router:
    def __init__(self, registry: ProviderRegistry, scoring: ScoringEngine, config: RoutingConfig):
        self._registry = registry
        self._scoring = scoring
        self._config = config

    def _preference_score(self, task_type: str, name: str) -> float:
        order = self._config.task_preferences.get(task_type, [])
        if name not in order:
            return UNLISTED_PREFERENCE
        return 1.0 - order.index(name) / len(order)

    def rank(self, task_type: str) -> list[str]:
        """Return available providers, best first. Raises if there are none."""
        available = self._registry.available_names()
        if not available:
            raise NoProviderAvailableError("No AI provider is configured.")

        candidates = [n for n in available if not self._scoring.is_cooling_down(n)] or available

        def final_score(name: str) -> float:
            return (
                self._config.preference_weight * self._preference_score(task_type, name)
                + self._config.performance_weight * self._scoring.score(name)
            )

        order = self._config.task_preferences.get(task_type, [])
        tiebreak = {name: i for i, name in enumerate(order)}
        return sorted(candidates, key=lambda n: (-final_score(n), tiebreak.get(n, len(order)), n))

    def plan(self, task_type: str, manual_choice: str | None = None) -> list[str]:
        """Ordered provider list: primary first, then fallbacks.

        A manual choice must be a configured provider and becomes the primary;
        the automatically ranked providers follow as fallbacks.
        """
        if manual_choice:
            if not self._registry.is_available(manual_choice):
                raise NoProviderAvailableError(f"Provider '{manual_choice}' is not configured.")
            rest = [n for n in self.rank(task_type) if n != manual_choice]
            return [manual_choice] + rest
        return self.rank(task_type)
