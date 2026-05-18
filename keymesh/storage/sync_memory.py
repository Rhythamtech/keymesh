"""
In-memory storage backend for synchronous contexts.

Zero dependencies. State is lost on process exit.
Default backend used by SyncKeyPool unless another is configured.
"""

import threading
from typing import Any

from keymesh.storage.sync_base import BaseSyncStorage


class SyncMemoryStorage(BaseSyncStorage):
    """
    Thread-safe in-memory state store.

    Backed by a simple dict + threading.Lock.
    Suitable for single-process, single-restart use cases.
    """

    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def save(self, key: str, state: dict[str, Any]) -> None:
        with self._lock:
            self._store[key] = dict(state)

    def load(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            return dict(self._store[key]) if key in self._store else None

    def load_all(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return {k: dict(v) for k, v in self._store.items()}

    def delete(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)

    def close(self) -> None:
        """No-op for in-memory backend."""
