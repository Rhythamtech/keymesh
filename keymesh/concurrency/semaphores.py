"""
Concurrency utilities for KeyMesh.

Provides a SemaphoreGroup for per-key concurrency limits — optional,
for users who want to cap in-flight requests per key.
"""

import asyncio
from collections import defaultdict


class SemaphoreGroup:
    """
    Per-key asyncio semaphore pool.

    Use this when you want to cap the number of concurrent in-flight
    requests per API key (e.g., a provider that allows max 5 concurrent calls).

    Example
    -------
    ```python
    sem_group = SemaphoreGroup(max_concurrent=5)

    key = await pool.acquire()
    async with sem_group.acquire(key):
        response = await client.call(api_key=key)
    await pool.release(key)
    ```
    """

    def __init__(self, max_concurrent: int = 10) -> None:
        self._max = max_concurrent
        self._sems: dict[str, asyncio.Semaphore] = defaultdict(
            lambda: asyncio.Semaphore(self._max)
        )

    def acquire(self, key: str) -> asyncio.Semaphore:
        """Return the semaphore for `key` (use as an async context manager)."""
        return self._sems[key]
