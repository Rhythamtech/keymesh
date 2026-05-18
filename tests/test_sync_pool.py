"""
Tests for SyncKeyPool — acquire, release, rate-limiting, and scheduling in a synchronous context.
"""

import pytest
from keymesh.pool.sync_pool import SyncKeyPool
from keymesh.scheduler.base import SchedulerStrategy
from keymesh.exceptions import NoAvailableKeyError, KeyExhaustedError


KEYS = ["sk-key-aaa111", "sk-key-bbb222", "sk-key-ccc333"]


@pytest.fixture
def pool() -> SyncKeyPool:
    return SyncKeyPool(keys=KEYS, strategy=SchedulerStrategy.ROUND_ROBIN)


def test_sync_acquire_returns_valid_key(pool: SyncKeyPool) -> None:
    key = pool.acquire()
    assert key in KEYS


def test_sync_release_updates_metrics(pool: SyncKeyPool) -> None:
    key = pool.acquire()
    pool.release(key, latency=0.3)
    status = pool.status()
    assert status["pool_metrics"]["total_acquires"] == 1
    assert status["pool_metrics"]["total_releases"] == 1


def test_sync_rate_limit_removes_key_temporarily(pool: SyncKeyPool) -> None:
    key = pool.acquire()
    pool.mark_rate_limited(key, cooldown=9999.0)
    remaining_count = pool.available_count()
    assert remaining_count == len(KEYS) - 1


def test_sync_mark_failed_exhausts_after_threshold() -> None:
    pool = SyncKeyPool(keys=["sk-only-key-xyz"], max_failures=2)
    key = pool.acquire()
    pool.mark_failed(key)  # failure 1 — no raise
    with pytest.raises(KeyExhaustedError):
        pool.mark_failed(key)  # failure 2 — exhausted


def test_sync_no_available_key_raises() -> None:
    # Use small acquire_timeout to speed up test execution
    pool = SyncKeyPool(keys=KEYS, strategy=SchedulerStrategy.ROUND_ROBIN, acquire_timeout=0.1)
    # Cool down all keys
    for key in KEYS:
        k = pool.acquire()
        pool.mark_rate_limited(k, cooldown=9999.0)
    with pytest.raises(NoAvailableKeyError):
        pool.acquire()


def test_sync_round_robin_rotates(pool: SyncKeyPool) -> None:
    keys_acquired = []
    for _ in range(len(KEYS)):
        k = pool.acquire()
        keys_acquired.append(k)
        pool.release(k)
    # Should have touched all keys
    assert set(keys_acquired) == set(KEYS)


def test_sync_all_strategies_acquire() -> None:
    for strategy in SchedulerStrategy:
        p = SyncKeyPool(keys=KEYS, strategy=strategy)
        k = p.acquire()
        assert k in KEYS


def test_sync_status_snapshot(pool: SyncKeyPool) -> None:
    status = pool.status()
    assert "pool_metrics" in status
    assert "keys" in status
    assert len(status["keys"]) == len(KEYS)


def test_sync_close(pool: SyncKeyPool) -> None:
    pool.close()  # Should not raise
