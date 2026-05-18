"""
Round-Robin scheduler — selects keys in strict sequential rotation.
"""

import threading
from typing import Sequence

from keymesh.scheduler.base import BaseScheduler, SchedulerStrategy
from keymesh.state.key_state import KeyState


class RoundRobinScheduler(BaseScheduler):
    """
    Distributes load evenly in a circular sequence.

    Thread-safe via a simple atomic counter protected by threading.Lock.
    Works correctly under both asyncio and multi-threaded environments.
    """

    strategy = SchedulerStrategy.ROUND_ROBIN

    def __init__(self) -> None:
        self._index: int = 0
        self._lock = threading.Lock()

    def select(self, candidates: Sequence[KeyState]) -> KeyState | None:
        if not candidates:
            return None

        with self._lock:
            idx = self._index % len(candidates)
            self._index = (self._index + 1) % len(candidates)

        return candidates[idx]
