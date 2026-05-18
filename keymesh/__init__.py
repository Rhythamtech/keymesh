"""
KeyMesh — Credential Orchestration Runtime for AI API Systems.

A lightweight, concurrency-safe API key pool manager and scheduler.
KeyMesh is NOT a proxy, SDK wrapper, or HTTP gateway.
It is purely a credential allocator and rate-limit-aware scheduler.

Usage:
    from keymesh import KeyPool, SchedulerStrategy

    pool = KeyPool(
        keys=["sk-key1", "sk-key2", "sk-key3"],
        strategy=SchedulerStrategy.LEAST_BUSY,
    )

    key = await pool.acquire()
    # ... use key in your own SDK/HTTP client ...
    await pool.release(key)
"""

from keymesh.pool.pool import KeyPool
from keymesh.pool.sync_pool import SyncKeyPool
from keymesh.scheduler.base import SchedulerStrategy
from keymesh.state.key_state import KeyState
from keymesh.state.sync_key_state import SyncKeyState
from keymesh.exceptions import (
    KeyMeshError,
    NoAvailableKeyError,
    KeyCooldownError,
    KeyExhaustedError,
)

__all__ = [
    "KeyPool",
    "SyncKeyPool",
    "SchedulerStrategy",
    "KeyState",
    "SyncKeyState",
    "KeyMeshError",
    "NoAvailableKeyError",
    "KeyCooldownError",
    "KeyExhaustedError",
]

__version__ = "0.1.0"
