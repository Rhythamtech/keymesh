"""
Storage backends for synchronous KeyMesh persistence.

Persistence is optional. The pool works fully in-memory by default.
Backends are used to survive restarts and share state across processes.
"""

from abc import ABC, abstractmethod
from typing import Any


class BaseSyncStorage(ABC):
    """
    Abstract storage interface for KeyMesh runtime state persistence in synchronous context.

    Implementations must be thread-safe (concurrent reads/writes OK).
    """

    @abstractmethod
    def save(self, key: str, state: dict[str, Any]) -> None:
        """Persist the state snapshot for `key`."""

    @abstractmethod
    def load(self, key: str) -> dict[str, Any] | None:
        """Load persisted state for `key`. Returns None if not found."""

    @abstractmethod
    def load_all(self) -> dict[str, dict[str, Any]]:
        """Load all persisted key states. Returns dict keyed by raw key string."""

    @abstractmethod
    def delete(self, key: str) -> None:
        """Remove persisted state for `key`."""

    @abstractmethod
    def close(self) -> None:
        """Release any held resources (connections, file handles)."""
