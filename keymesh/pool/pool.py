"""
KeyPool — the central public interface of KeyMesh.

Responsibilities:
  - Hold and manage a pool of KeyState objects
  - Delegate key selection to the configured scheduler
  - Enforce cooldowns, failure thresholds, and retry logic
  - Surface a minimal public API: acquire / release / mark_failed / mark_rate_limited

KeyPool is framework-agnostic. It never sends HTTP requests or wraps any SDK.
"""

import asyncio
import logging
from typing import Any, Sequence

from keymesh.exceptions import KeyExhaustedError, NoAvailableKeyError
from keymesh.metrics.pool_metrics import PoolMetrics
from keymesh.scheduler import BaseScheduler, SchedulerStrategy, build_scheduler
from keymesh.state.key_state import KeyState
from keymesh.storage.base import BaseStorage
from keymesh.storage.memory import MemoryStorage

logger = logging.getLogger(__name__)


class KeyPool:
    """
    Manages a collection of API keys with scheduling, cooldown, and retry support.

    Example
    -------
    ```python
    pool = KeyPool(keys=["sk-a", "sk-b", "sk-c"])

    key = await pool.acquire()
    try:
        response = await my_client.call(api_key=key)
        await pool.release(key, latency=response.elapsed)
    except RateLimitError:
        await pool.mark_rate_limited(key, cooldown=60.0)
    except Exception:
        await pool.mark_failed(key)
    ```
    """

    def __init__(
        self,
        keys: Sequence[str],
        *,
        strategy: SchedulerStrategy = SchedulerStrategy.LEAST_BUSY,
        scheduler: BaseScheduler | None = None,
        storage: BaseStorage | None = None,
        default_cooldown: float = 60.0,
        max_failures: int = 10,
        acquire_timeout: float = 30.0,
    ) -> None:
        """
        Parameters
        ----------
        keys:
            List of raw API key strings. Must be non-empty.
        strategy:
            Scheduling strategy to use. Ignored if `scheduler` is provided.
        scheduler:
            Custom scheduler instance. Overrides `strategy`.
        storage:
            Persistence backend. Defaults to in-memory (no persistence).
        default_cooldown:
            Default cooldown duration in seconds when mark_rate_limited is called.
        max_failures:
            Consecutive failures before a key is considered exhausted.
        acquire_timeout:
            Max seconds to wait for an available key before raising NoAvailableKeyError.
        """
        if not keys:
            raise ValueError("KeyPool requires at least one API key.")

        self._states: dict[str, KeyState] = {
            k: KeyState(key=k, max_failures=max_failures) for k in keys
        }
        self._scheduler: BaseScheduler = scheduler or build_scheduler(strategy)
        self._storage: BaseStorage = storage or MemoryStorage()
        self._default_cooldown = default_cooldown
        self._max_failures = max_failures
        self._acquire_timeout = acquire_timeout
        self._metrics = PoolMetrics()
        self._pool_lock = asyncio.Lock()

        logger.info(
            "KeyPool initialised: %d keys, strategy=%s",
            len(keys),
            self._scheduler.strategy,
        )

    # ── Public API ────────────────────────────────────────────────────────────────

    async def acquire(self) -> str:
        """
        Acquire an available API key.

        Blocks (up to `acquire_timeout`) until a key becomes available.

        Returns
        -------
        str
            The raw API key string to inject into your HTTP client / SDK.

        Raises
        ------
        NoAvailableKeyError
            If no key becomes available within `acquire_timeout` seconds.
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._acquire_timeout

        while True:
            key_state = await self._try_acquire()
            if key_state is not None:
                self._metrics.record_acquire()
                logger.debug("Acquired key ...%s", key_state.key[-6:])
                return key_state.key

            self._metrics.record_no_key()
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise NoAvailableKeyError(
                    "No API keys are currently available. "
                    "All keys are either cooling down or exhausted."
                )

            # Brief sleep before retrying to avoid busy-loop
            await asyncio.sleep(min(0.5, remaining))

    async def release(self, key: str, *, latency: float = 0.0) -> None:
        """
        Release a key after a successful API call.

        Parameters
        ----------
        key:
            The key string returned by acquire().
        latency:
            Optional: elapsed seconds for the call (used for weighted scheduling).
        """
        state = self._resolve(key)
        await state.record_success(latency)
        self._metrics.record_release()
        await self._storage.save(key, state.snapshot())
        logger.debug("Released key ...%s (latency=%.3fs)", key[-6:], latency)

    async def mark_failed(self, key: str) -> None:
        """
        Mark a key as failed (non-rate-limit error).

        After `max_failures` calls, the key is marked exhausted and excluded
        from future scheduling.

        Raises
        ------
        KeyExhaustedError
            If the key has now reached the failure threshold.
        """
        state = self._resolve(key)
        await state.record_failure()
        self._metrics.record_failure()
        await self._storage.save(key, state.snapshot())
        logger.warning("Key ...%s marked failed (total=%d)", key[-6:], state.failure_count)

        if state.is_exhausted:
            raise KeyExhaustedError(key)

    async def mark_rate_limited(self, key: str, *, cooldown: float | None = None) -> None:
        """
        Mark a key as rate-limited (HTTP 429).

        The key will be excluded from scheduling until the cooldown elapses.
        Resets the key's consecutive failure counter — a rate-limited key is
        still valid, just throttled.

        Parameters
        ----------
        cooldown:
            Cooldown duration in seconds. Defaults to pool's `default_cooldown`.
        """
        duration = cooldown if cooldown is not None else self._default_cooldown
        state = self._resolve(key)
        await state.apply_cooldown(duration)
        self._metrics.record_cooldown()
        await self._storage.save(key, state.snapshot())
        logger.warning(
            "Key ...%s rate-limited, cooling down for %.1fs", key[-6:], duration
        )

    async def add_key(self, key: str) -> None:
        """
        Add or reset a key in the pool at runtime.

        Use this to:
        - Re-admit an exhausted key after rotating/refreshing it.
        - Inject a brand-new key into a running pool without restarting.

        Parameters
        ----------
        key:
            The raw API key string to add or reset.
        """
        async with self._pool_lock:
            self._states[key] = KeyState(key=key, max_failures=self._max_failures)
        logger.info("Key ...%s added/reset in pool", key[-6:])

    # ── Diagnostics ───────────────────────────────────────────────────────────────

    def status(self) -> dict[str, Any]:
        """Return a full status snapshot of the pool and all key states."""
        return {
            "pool_metrics": self._metrics.snapshot(),
            "scheduler": self._scheduler.strategy,
            "keys": [ks.snapshot() for ks in self._states.values()],
        }

    def available_count(self) -> int:
        """Number of keys currently available for scheduling."""
        return sum(1 for ks in self._states.values() if ks.is_available)

    # ── Internal ──────────────────────────────────────────────────────────────────

    async def _try_acquire(self) -> KeyState | None:
        """
        Ask the scheduler to pick one available key.

        Returns None if no key is available right now.
        """
        async with self._pool_lock:
            candidates = [ks for ks in self._states.values() if ks.is_available]
            key_state = self._scheduler.select(candidates)
            if key_state is not None:
                await key_state.increment_active()
            return key_state

    def _resolve(self, key: str) -> KeyState:
        """Look up a KeyState by raw key string. Raises KeyError if unknown."""
        try:
            return self._states[key]
        except KeyError as exc:
            raise KeyError(f"Unknown key '...{key[-6:]}' — was it added to this pool?") from exc

    async def close(self) -> None:
        """Release storage resources. Call when pool is no longer needed."""
        await self._storage.close()
        logger.info("KeyPool closed.")
