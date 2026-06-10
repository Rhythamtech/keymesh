"""
Tests for KeyPool — acquire, release, rate-limiting, and scheduling.
"""

import pytest
from keymesh.pool.pool import KeyPool
from keymesh.scheduler.base import SchedulerStrategy
from keymesh.exceptions import NoAvailableKeyError, KeyExhaustedError


KEYS = ["sk-key-aaa111", "sk-key-bbb222", "sk-key-ccc333"]


@pytest.fixture
def pool() -> KeyPool:
    return KeyPool(keys=KEYS, strategy=SchedulerStrategy.ROUND_ROBIN)


@pytest.mark.asyncio
async def test_acquire_returns_valid_key(pool: KeyPool) -> None:
    key = await pool.acquire()
    assert key in KEYS


@pytest.mark.asyncio
async def test_release_updates_metrics(pool: KeyPool) -> None:
    key = await pool.acquire()
    await pool.release(key, latency=0.3)
    status = pool.status()
    assert status["pool_metrics"]["total_acquires"] == 1
    assert status["pool_metrics"]["total_releases"] == 1


@pytest.mark.asyncio
async def test_rate_limit_removes_key_temporarily(pool: KeyPool) -> None:
    key = await pool.acquire()
    await pool.mark_rate_limited(key, cooldown=9999.0)
    remaining_count = pool.available_count()
    assert remaining_count == len(KEYS) - 1


@pytest.mark.asyncio
async def test_mark_failed_exhausts_after_threshold() -> None:
    pool = KeyPool(keys=["sk-only-key-xyz"], max_failures=2)
    key = await pool.acquire()
    await pool.mark_failed(key)  # failure 1 — no raise
    with pytest.raises(KeyExhaustedError):
        await pool.mark_failed(key)  # failure 2 — exhausted


@pytest.mark.asyncio
async def test_no_available_key_raises(pool: KeyPool) -> None:
    # Cool down all keys
    for key in KEYS:
        k = await pool.acquire()
        await pool.mark_rate_limited(k, cooldown=9999.0)
    with pytest.raises(NoAvailableKeyError):
        await pool.acquire()


@pytest.mark.asyncio
async def test_round_robin_rotates(pool: KeyPool) -> None:
    keys_acquired = []
    for _ in range(len(KEYS)):
        k = await pool.acquire()
        keys_acquired.append(k)
        await pool.release(k)
    # Should have touched all keys
    assert set(keys_acquired) == set(KEYS)


@pytest.mark.asyncio
async def test_all_strategies_acquire(pool: KeyPool) -> None:
    for strategy in SchedulerStrategy:
        p = KeyPool(keys=KEYS, strategy=strategy)
        k = await p.acquire()
        assert k in KEYS


@pytest.mark.asyncio
async def test_status_snapshot(pool: KeyPool) -> None:
    status = pool.status()
    assert "pool_metrics" in status
    assert "keys" in status
    assert len(status["keys"]) == len(KEYS)


@pytest.mark.asyncio
async def test_close(pool: KeyPool) -> None:
    await pool.close()  # Should not raise
