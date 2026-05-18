"""
Weighted scheduler — selects keys proportional to their health score.

Health score incorporates: success rate, average latency, and availability.
"""

import random
from typing import Sequence

from keymesh.scheduler.base import BaseScheduler, SchedulerStrategy
from keymesh.state.key_state import KeyState


class WeightedScheduler(BaseScheduler):
    """
    Probabilistic weighted selection based on composite key health score.

    Healthier keys (high success rate, low latency, no cooldown) are
    selected more frequently. Falls back to uniform selection if all
    weights are zero.
    """

    strategy = SchedulerStrategy.WEIGHTED

    def select(self, candidates: Sequence[KeyState]) -> KeyState | None:
        if not candidates:
            return None

        weights = [ks.health_score for ks in candidates]
        total = sum(weights)

        if total == 0.0:
            # All scores are 0 — fall back to random uniform selection
            return random.choice(candidates)  # noqa: S311

        # Weighted random selection
        r = random.uniform(0.0, total)  # noqa: S311
        cumulative = 0.0
        for key_state, weight in zip(candidates, weights, strict=True):
            cumulative += weight
            if r <= cumulative:
                return key_state

        return candidates[-1]  # numerical safety fallback
