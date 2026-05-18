"""
Runtime metrics aggregation for the pool.
"""

import time
from dataclasses import dataclass, field


@dataclass
class PoolMetrics:
    """Aggregated runtime metrics for a KeyPool instance."""

    total_acquires: int = 0
    total_releases: int = 0
    total_failures: int = 0
    total_cooldowns: int = 0
    total_retries: int = 0
    no_key_available_count: int = 0
    _started_at: float = field(default_factory=time.monotonic, init=False)

    def record_acquire(self) -> None:
        self.total_acquires += 1

    def record_release(self) -> None:
        self.total_releases += 1

    def record_failure(self) -> None:
        self.total_failures += 1

    def record_cooldown(self) -> None:
        self.total_cooldowns += 1

    def record_retry(self) -> None:
        self.total_retries += 1

    def record_no_key(self) -> None:
        self.no_key_available_count += 1

    @property
    def uptime_seconds(self) -> float:
        return time.monotonic() - self._started_at

    def snapshot(self) -> dict:
        return {
            "uptime_seconds": round(self.uptime_seconds, 2),
            "total_acquires": self.total_acquires,
            "total_releases": self.total_releases,
            "total_failures": self.total_failures,
            "total_cooldowns": self.total_cooldowns,
            "total_retries": self.total_retries,
            "no_key_available_count": self.no_key_available_count,
        }
