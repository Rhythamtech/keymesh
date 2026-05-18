"""
SyncKeyPool — the central public interface of KeyMesh for synchronous/threaded environments.

Responsibilities:
  - Hold and manage a pool of SyncKeyState objects
  - Delegate key selection to the configured scheduler
  - Enforce cooldowns, failure thresholds, and retry logic
  - Surface a minimal public API: acquire / release / mark_failed / mark_rate_limited

SyncKeyPool is thread-safe and blocking.
"""

import logging
import threading
import time
from typing import Sequence

from keymesh.exceptions import KeyExhaustedError, NoAvailableKeyError
from keymesh.metrics.pool_metrics import PoolMetrics
from keymesh.scheduler import BaseScheduler, SchedulerStrategy, build_scheduler
from keymesh.state.sync_key_state import SyncKeyState
from keymesh.storage.sync_base import BaseSyncStorage
from keymesh.storage.sync_memory import SyncMemoryStorage

logger = logging.getLogger(__name__)


class SyncKeyPool:
    """
    Manages a collection of API keys synchronously with scheduling, cooldown, and retry support.

    Example
    -------
    ```python
    pool = SyncKeyPool(keys=["sk-a", "sk-b", "sk-c"])

    key = pool.acquire()
    try:
        response = my_client.call(api_key=key)
        pool.release(key, latency=response.elapsed)
    except RateLimitError:
        pool.mark_rate_limited(key, cooldown=60.0)
    except Exception:
        pool.mark_failed(key)
    ```
    """

    def __init__(
        self,
        keys: Sequence[str],
        *,
        strategy: SchedulerStrategy = SchedulerStrategy.LEAST_BUSY,
        scheduler: BaseScheduler | None = None,
        storage: BaseSyncStorage | None = None,
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
            raise ValueError("SyncKeyPool requires at least one API key.")

        self._states: dict[str, SyncKeyState] = {
            k: SyncKeyState(key=k, max_failures=max_failures) for k in keys
        }
        self._scheduler: BaseScheduler = scheduler or build_scheduler(strategy)
        self._storage: BaseSyncStorage = storage or SyncMemoryStorage()
        self._default_cooldown = default_cooldown
        self._acquire_timeout = acquire_timeout
        self._metrics = PoolMetrics()
        self._pool_lock = threading.Lock()

        logger.info(
            "SyncKeyPool initialised: %d keys, strategy=%s",
            len(keys),
            self._scheduler.strategy,
        )

    # ── Public API ────────────────────────────────────────────────────────────────

    def acquire(self) -> str:
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
        deadline = time.monotonic() + self._acquire_timeout

        while True:
            key_state = self._try_acquire()
            if key_state is not None:
                key_state.increment_active()
                self._metrics.record_acquire()
                logger.debug("Acquired key ...%s", key_state.key[-6:])
                return key_state.key

            self._metrics.record_no_key()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise NoAvailableKeyError(
                    "No API keys are currently available. "
                    "All keys are either cooling down or exhausted."
                )

            # Brief sleep before retrying to avoid busy-loop
            time.sleep(min(0.5, remaining))

    def release(self, key: str, *, latency: float = 0.0) -> None:
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
        state.record_success(latency)
        self._metrics.record_release()
        self._storage.save(key, state.snapshot())
        logger.debug("Released key ...%s (latency=%.3fs)", key[-6:], latency)

    def mark_failed(self, key: str) -> None:
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
        state.record_failure()
        self._metrics.record_failure()
        self._storage.save(key, state.snapshot())
        logger.warning("Key ...%s marked failed (total=%d)", key[-6:], state.failure_count)

        if state.is_exhausted:
            raise KeyExhaustedError(key)

    def mark_rate_limited(self, key: str, *, cooldown: float | None = None) -> None:
        """
        Mark a key as rate-limited (HTTP 429).

        The key will be excluded from scheduling until the cooldown elapses.

        Parameters
        ----------
        cooldown:
            Cooldown duration in seconds. Defaults to pool's `default_cooldown`.
        """
        duration = cooldown if cooldown is not None else self._default_cooldown
        state = self._resolve(key)
        state.apply_cooldown(duration)
        self._metrics.record_cooldown()
        self._storage.save(key, state.snapshot())
        logger.warning(
            "Key ...%s rate-limited, cooling down for %.1fs", key[-6:], duration
        )

    # ── Diagnostics ───────────────────────────────────────────────────────────────

    def status(self) -> dict:
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

    def _try_acquire(self) -> SyncKeyState | None:
        """
        Ask the scheduler to pick one available key.

        Returns None if no key is available right now.
        """
        with self._pool_lock:
            candidates = [ks for ks in self._states.values() if ks.is_available]
            # Schedulers are stateless selectors and conform to BaseScheduler,
            # which works on SyncKeyState since it has identical properties/duck-types KeyState.
            return self._scheduler.select(candidates)  # type: ignore

    def _resolve(self, key: str) -> SyncKeyState:
        """Look up a SyncKeyState by raw key string. Raises KeyError if unknown."""
        try:
            return self._states[key]
        except KeyError as exc:
            raise KeyError(f"Unknown key '...{key[-6:]}' — was it added to this pool?") from exc

    def close(self) -> None:
        """Release storage resources. Call when pool is no longer needed."""
        self._storage.close()
        logger.info("SyncKeyPool closed.")
