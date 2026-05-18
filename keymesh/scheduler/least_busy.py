"""
Least-Busy scheduler — prefers keys with the fewest active concurrent requests.
"""

from typing import Sequence

from keymesh.scheduler.base import BaseScheduler, SchedulerStrategy
from keymesh.state.key_state import KeyState


class LeastBusyScheduler(BaseScheduler):
    """
    Selects the key currently handling the fewest active requests.

    Ties are broken by last_used (oldest first), which spreads load
    more evenly when multiple keys have 0 active requests.
    """

    strategy = SchedulerStrategy.LEAST_BUSY

    def select(self, candidates: Sequence[KeyState]) -> KeyState | None:
        if not candidates:
            return None

        return min(
            candidates,
            key=lambda ks: (ks.active_requests, ks.last_used),
        )
