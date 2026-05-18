"""
In-memory storage backend.

Zero dependencies. State is lost on process exit.
Default backend used by KeyPool unless another is configured.
"""

import asyncio
from typing import Any

from keymesh.storage.base import BaseStorage


class MemoryStorage(BaseStorage):
    """
    Thread-safe in-memory state store.

    Backed by a simple dict + asyncio.Lock.
    Suitable for single-process, single-restart use cases.
    """

    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def save(self, key: str, state: dict[str, Any]) -> None:
        async with self._lock:
            self._store[key] = dict(state)

    async def load(self, key: str) -> dict[str, Any] | None:
        async with self._lock:
            return dict(self._store[key]) if key in self._store else None

    async def load_all(self) -> dict[str, dict[str, Any]]:
        async with self._lock:
            return {k: dict(v) for k, v in self._store.items()}

    async def delete(self, key: str) -> None:
        async with self._lock:
            self._store.pop(key, None)

    async def close(self) -> None:
        """No-op for in-memory backend."""
