"""
KeyState — Runtime state for a single API key.

Tracks: active requests, cooldown, success/failure counts, latency, and last-use timestamp.
All mutations are protected by an asyncio.Lock for concurrency safety.
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class KeyState:
    """
    Immutable identity + mutable runtime state for one API credential.

    All state mutations must go through the update_* helpers which
    acquire the internal lock — never mutate fields directly.
    """

    key: str
    """The raw API key string. Treat as opaque — KeyMesh never inspects its contents."""

    # ── Runtime counters ────────────────────────────────────────────────────────
    active_requests: int = field(default=0, init=False)
    cooldown_until: float = field(default=0.0, init=False)
    success_count: int = field(default=0, init=False)
    failure_count: int = field(default=0, init=False)
    latency_avg: float = field(default=0.0, init=False)
    last_used: float = field(default=0.0, init=False)

    # ── Concurrency primitive ────────────────────────────────────────────────────
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)

    # ── Config ──────────────────────────────────────────────────────────────────
    max_failures: int = 10
    """After this many consecutive failures, key is considered exhausted."""

    # ── Derived properties ───────────────────────────────────────────────────────

    @property
    def is_cooling_down(self) -> bool:
        """True if the key is currently in cooldown (rate-limited)."""
        return time.monotonic() < self.cooldown_until

    @property
    def cooldown_remaining(self) -> float:
        """Seconds remaining in cooldown; 0.0 if not cooling down."""
        remaining = self.cooldown_until - time.monotonic()
        return max(0.0, remaining)

    @property
    def is_exhausted(self) -> bool:
        """True if failure count has exceeded the max_failures threshold."""
        return self.failure_count >= self.max_failures

    @property
    def is_available(self) -> bool:
        """True if the key can accept a new request right now."""
        return not self.is_cooling_down and not self.is_exhausted

    @property
    def health_score(self) -> float:
        """
        Composite health score in [0.0, 1.0].

        Higher = healthier. Used by the weighted scheduler.
        Formula: success_rate * (1 / (1 + latency_avg)) * availability_factor
        """
        total = self.success_count + self.failure_count
        success_rate = self.success_count / total if total > 0 else 1.0
        latency_factor = 1.0 / (1.0 + self.latency_avg)
        availability_factor = 0.0 if not self.is_available else 1.0
        return success_rate * latency_factor * availability_factor

    # ── Mutation helpers (all async, lock-protected) ─────────────────────────────

    async def increment_active(self) -> None:
        """Record that a new request is using this key."""
        async with self._lock:
            self.active_requests += 1
            self.last_used = time.monotonic()

    async def decrement_active(self) -> None:
        """Record that a request using this key has completed."""
        async with self._lock:
            self.active_requests = max(0, self.active_requests - 1)

    async def record_success(self, latency: float) -> None:
        """
        Record a successful API call.

        Updates success count and running latency average using
        exponential moving average (alpha=0.2).
        """
        async with self._lock:
            self.success_count += 1
            self.active_requests = max(0, self.active_requests - 1)
            alpha = 0.2
            if self.latency_avg == 0.0:
                self.latency_avg = latency
            else:
                self.latency_avg = alpha * latency + (1 - alpha) * self.latency_avg

    async def record_failure(self) -> None:
        """Record a failed API call (non-rate-limit failure)."""
        async with self._lock:
            self.failure_count += 1
            self.active_requests = max(0, self.active_requests - 1)

    async def apply_cooldown(self, duration: float = 60.0) -> None:
        """
        Put the key into cooldown for `duration` seconds.

        Called on HTTP 429 responses. Also resets the consecutive failure
        counter — a rate-limited key is still valid, just throttled.
        """
        async with self._lock:
            self.cooldown_until = time.monotonic() + duration
            self.active_requests = max(0, self.active_requests - 1)
            self.failure_count = 0  # key is still valid — reset consecutive failures

    async def reset_failures(self) -> None:
        """Reset failure counter (e.g., after cooldown expires)."""
        async with self._lock:
            self.failure_count = 0

    def snapshot(self) -> dict[str, Any]:
        """Return a serialisable point-in-time snapshot of this key's state."""
        return {
            "key_suffix": f"...{self.key[-6:]}",
            "active_requests": self.active_requests,
            "cooldown_until": self.cooldown_until,
            "cooldown_remaining": round(self.cooldown_remaining, 2),
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "latency_avg": round(self.latency_avg, 4),
            "last_used": self.last_used,
            "is_available": self.is_available,
            "health_score": round(self.health_score, 4),
        }

    def __repr__(self) -> str:
        return (
            f"KeyState(key=...{self.key[-6:]!r}, "
            f"active={self.active_requests}, "
            f"available={self.is_available}, "
            f"health={self.health_score:.2f})"
        )
