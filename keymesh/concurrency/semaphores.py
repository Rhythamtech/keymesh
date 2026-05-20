"""
Concurrency utilities for KeyMesh.

Provides a SemaphoreGroup for per-key concurrency limits — optional,
for users who want to cap in-flight requests per key.
"""

import asyncio


class SemaphoreGroup:
    """
    Per-key asyncio semaphore pool.

    Use this when you want to cap the number of concurrent in-flight
    requests per API key (e.g., a provider that allows max 5 concurrent calls).

    Semaphores are created lazily on first use inside a running event loop,
    avoiding "Future attached to a different loop" errors when this object
    is instantiated at module level or before ``asyncio.run()`` is called.

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
        self._sems: dict[str, asyncio.Semaphore] = {}

    def acquire(self, key: str) -> asyncio.Semaphore:
        """Return (or lazily create) the semaphore for `key`.

        Must be called from within a running async context so that the
        semaphore is bound to the correct event loop.
        """
        if key not in self._sems:
            # Created inside a coroutine: the running loop is guaranteed.
            self._sems[key] = asyncio.Semaphore(self._max)
        return self._sems[key]
