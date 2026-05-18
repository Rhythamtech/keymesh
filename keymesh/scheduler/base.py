"""
Scheduler base — strategy enum and abstract base class.
"""

import enum
from abc import ABC, abstractmethod
from typing import Sequence

from keymesh.state.key_state import KeyState


class SchedulerStrategy(str, enum.Enum):
    """Built-in scheduling strategies."""

    ROUND_ROBIN = "round_robin"
    LEAST_BUSY = "least_busy"
    WEIGHTED = "weighted"


class BaseScheduler(ABC):
    """
    Abstract base for all KeyMesh schedulers.

    Schedulers are stateless selectors: given a list of KeyState objects,
    they return the best candidate. They do NOT mutate state.
    """

    strategy: SchedulerStrategy

    @abstractmethod
    def select(self, candidates: Sequence[KeyState]) -> KeyState | None:
        """
        Select the best available key from `candidates`.

        Args:
            candidates: All currently available (not cooling down, not exhausted) keys.

        Returns:
            The selected KeyState, or None if no candidate is viable.
        """
