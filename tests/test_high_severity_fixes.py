"""
Tests covering high-severity fixes:
1. add_key() in KeyPool and SyncKeyPool (recovery from exhaustion & runtime pool changes).
2. Key hashing in JSONStorage & SyncJSONStorage.
3. DeprecationWarning in CooldownManager.apply().
4. Lazy initialization in SemaphoreGroup.
"""

import asyncio
import hashlib
import json
import pytest
import warnings
from pathlib import Path

from keymesh.pool.pool import KeyPool
from keymesh.pool.sync_pool import SyncKeyPool
from keymesh.exceptions import KeyExhaustedError, NoAvailableKeyError
from keymesh.storage.json_storage import JSONStorage
from keymesh.storage.sync_json import SyncJSONStorage
from keymesh.cooldown.manager import CooldownManager
from keymesh.concurrency.semaphores import SemaphoreGroup
from keymesh.scheduler.base import SchedulerStrategy


@pytest.mark.asyncio
async def test_add_key_async() -> None:
    pool = KeyPool(keys=["key1"], max_failures=1, acquire_timeout=0.1)
    
    # 1. Exhaust the key
    k = await pool.acquire()
    with pytest.raises(KeyExhaustedError):
        await pool.mark_failed(k)
        
    # Pool should now be exhausted
    with pytest.raises(NoAvailableKeyError):
        await pool.acquire()
        
    # 2. Re-admit the key via add_key()
    await pool.add_key("key1")
    
    # It should be available again
    k2 = await pool.acquire()
    assert k2 == "key1"
    await pool.release(k2)
    
    # 3. Add a brand new key at runtime
    await pool.add_key("new_key_at_runtime")
    
    # Verify that the new key is scheduled and usable
    assert pool.available_count() == 2


def test_add_key_sync() -> None:
    pool = SyncKeyPool(keys=["key1"], max_failures=1, acquire_timeout=0.1)
    
    # 1. Exhaust the key
    k = pool.acquire()
    with pytest.raises(KeyExhaustedError):
        pool.mark_failed(k)
        
    # Pool should now be exhausted
    with pytest.raises(NoAvailableKeyError):
        pool.acquire()
        
    # 2. Re-admit the key via add_key()
    pool.add_key("key1")
    
    # It should be available again
    k2 = pool.acquire()
    assert k2 == "key1"
    pool.release(k2)
    
    # 3. Add a brand new key at runtime
    pool.add_key("new_key_at_runtime")
    
    # Verify that the new key is scheduled and usable
    assert pool.available_count() == 2


@pytest.mark.asyncio
async def test_json_storage_hashes_keys(tmp_path: Path) -> None:
    storage_path = tmp_path / "test_state.json"
    storage = JSONStorage(path=storage_path)
    
    raw_key = "sk-very-secret-token-123456"
    hashed_key_prefix = hashlib.sha256(raw_key.encode()).hexdigest()[:16]
    
    state_data = {"success_count": 5, "failure_count": 0}
    await storage.save(raw_key, state_data)
    
    # Check that we can load it back
    loaded = await storage.load(raw_key)
    assert loaded == state_data
    
    # Verify file content DOES NOT contain raw key, but DOES contain the hash prefix
    file_text = storage_path.read_text(encoding="utf-8")
    assert raw_key not in file_text
    assert hashed_key_prefix in file_text
    
    # Verify load_all and delete
    all_states = await storage.load_all()
    assert hashed_key_prefix in all_states
    
    await storage.delete(raw_key)
    assert await storage.load(raw_key) is None


def test_sync_json_storage_hashes_keys(tmp_path: Path) -> None:
    storage_path = tmp_path / "test_sync_state.json"
    storage = SyncJSONStorage(path=storage_path)
    
    raw_key = "sk-another-secret-token-98765"
    hashed_key_prefix = hashlib.sha256(raw_key.encode()).hexdigest()[:16]
    
    state_data = {"success_count": 10, "failure_count": 1}
    storage.save(raw_key, state_data)
    
    # Check loading back
    loaded = storage.load(raw_key)
    assert loaded == state_data
    
    # Verify file content has hashed key, not raw key
    file_text = storage_path.read_text(encoding="utf-8")
    assert raw_key not in file_text
    assert hashed_key_prefix in file_text
    
    # Verify load_all and delete
    all_states = storage.load_all()
    assert hashed_key_prefix in all_states
    
    storage.delete(raw_key)
    assert storage.load(raw_key) is None


def test_cooldown_manager_deprecation_warning() -> None:
    pool = SyncKeyPool(keys=["k1"])
    state = pool._resolve("k1")  # retrieve KeyState object via async pool helper or resolve
    
    # Resolve for KeyPool
    async def get_async_state() -> object:
        p = KeyPool(keys=["k1"])
        return p._resolve("k1")
        
    loop = asyncio.new_event_loop()
    async_state = loop.run_until_complete(get_async_state())
    loop.close()
    
    with pytest.warns(DeprecationWarning) as record:
        CooldownManager.apply(async_state, duration=10.0)  # type: ignore
        
    assert len(record) > 0
    assert "CooldownManager.apply() is not concurrency-safe" in str(record[0].message)


def test_semaphore_group_lazy_initialization() -> None:
    # Creating group outside any loop (e.g. at import time or app instantiation)
    group = SemaphoreGroup(max_concurrent=3)
    
    # Loop 1: Acquire key-a semaphore and use it
    loop1 = asyncio.new_event_loop()
    
    async def use_sem1() -> None:
        sem = group.acquire("key-a")
        async with sem:
            pass
            
    loop1.run_until_complete(use_sem1())
    loop1.close()
    
    # Loop 2: Acquire key-b semaphore in a separate loop and use it.
    # This proves lazy creation inside the active event loop avoids event loop mismatch errors.
    loop2 = asyncio.new_event_loop()
    
    async def use_sem2() -> None:
        sem = group.acquire("key-b")
        async with sem:
            pass
            
    loop2.run_until_complete(use_sem2())
    loop2.close()

