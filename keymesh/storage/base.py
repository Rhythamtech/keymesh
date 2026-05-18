"""
Storage backends for KeyMesh persistence.

Persistence is optional. The pool works fully in-memory by default.
Backends are used to survive restarts and share state across processes.
"""

from abc import ABC, abstractmethod
from typing import Any


class BaseStorage(ABC):
    """
    Abstract storage interface for KeyMesh runtime state persistence.

    Implementations must be async-safe (concurrent reads/writes OK).
    """

    @abstractmethod
    async def save(self, key: str, state: dict[str, Any]) -> None:
        """Persist the state snapshot for `key`."""

    @abstractmethod
    async def load(self, key: str) -> dict[str, Any] | None:
        """Load persisted state for `key`. Returns None if not found."""

    @abstractmethod
    async def load_all(self) -> dict[str, dict[str, Any]]:
        """Load all persisted key states. Returns dict keyed by raw key string."""

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Remove persisted state for `key`."""

    @abstractmethod
    async def close(self) -> None:
        """Release any held resources (connections, file handles)."""
