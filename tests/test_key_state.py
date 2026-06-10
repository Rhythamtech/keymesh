"""
Tests for KeyState runtime state tracking.
"""

import time
import pytest
from keymesh.state.key_state import KeyState


@pytest.fixture
def state() -> KeyState:
    return KeyState(key="sk-test-key-abcdef", max_failures=3)


def test_initial_state(state: KeyState) -> None:
    assert state.active_requests == 0
    assert state.failure_count == 0
    assert state.success_count == 0
    assert state.latency_avg == 0.0
    assert not state.is_cooling_down
    assert not state.is_exhausted
    assert state.is_available


@pytest.mark.asyncio
async def test_increment_decrement_active(state: KeyState) -> None:
    await state.increment_active()
    assert state.active_requests == 1
    await state.decrement_active()
    assert state.active_requests == 0


@pytest.mark.asyncio
async def test_record_success_updates_latency(state: KeyState) -> None:
    await state.record_success(latency=0.5)
    assert state.success_count == 1
    assert state.latency_avg == pytest.approx(0.5)
    await state.record_success(latency=1.0)
    assert state.success_count == 2
    # EMA with alpha=0.2: 0.2*1.0 + 0.8*0.5 = 0.6
    assert state.latency_avg == pytest.approx(0.6)


@pytest.mark.asyncio
async def test_cooldown(state: KeyState) -> None:
    await state.apply_cooldown(duration=5.0)
    assert state.is_cooling_down
    assert not state.is_available
    assert state.cooldown_remaining == pytest.approx(5.0, abs=0.1)


@pytest.mark.asyncio
async def test_exhaustion(state: KeyState) -> None:
    for _ in range(3):
        await state.record_failure()
    assert state.is_exhausted
    assert not state.is_available


def test_health_score_fresh_key(state: KeyState) -> None:
    # Fresh key has no history — defaults to 1.0 success rate, 0 latency
    assert state.health_score == pytest.approx(1.0)


def test_health_score_unavailable_key(state: KeyState) -> None:
    # Manually set cooldown (sync, for test speed)
    state.cooldown_until = time.monotonic() + 30
    assert state.health_score == pytest.approx(0.0)


def test_snapshot_keys(state: KeyState) -> None:
    snap = state.snapshot()
    assert "key_suffix" in snap
    assert "health_score" in snap
    assert "is_available" in snap
