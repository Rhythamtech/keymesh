# KeyMesh — Real-World Implementation Problems & Solutions

A comprehensive analysis of issues that will manifest when deploying KeyMesh in real production workloads. Each problem is ranked by severity, accompanied by a root cause analysis and a concrete fix.

---

## Problem Index

| # | Problem | Severity | Area |
|---|---------|----------|------|
| 1 | [Key Leak on Unhandled Exception Paths](#1-key-leak-on-unhandled-exception-paths) | 🔴 Critical | `pool.py`, `example.py` |
| 2 | [Race Window Between `_try_acquire` and `increment_active`](#2-race-window-between-_try_acquire-and-increment_active) | 🔴 Critical | `pool.py`, `key_state.py` |
| 3 | [Deprecated `get_event_loop()` in `acquire()`](#3-deprecated-get_event_loop-in-acquire) | 🟠 High | `pool.py` |
| 4 | [Exhausted Keys Are Never Re-admitted](#4-exhausted-keys-are-never-re-admitted) | 🟠 High | `key_state.py`, `pool.py` |
| 5 | [Cooldown Manager Mutates State Without Lock](#5-cooldown-manager-mutates-state-without-lock) | 🟠 High | `cooldown/manager.py` |
| 6 | [JSON Storage Writes Raw API Keys to Disk](#6-json-storage-writes-raw-api-keys-to-disk) | 🟠 High | `storage/json_storage.py` |
| 7 | [SemaphoreGroup Creates Semaphores in Wrong Event Loop](#7-semaphoregroup-creates-semaphores-in-wrong-event-loop) | 🟠 High | `concurrency/semaphores.py` |
| 8 | [No Per-Key Concurrency Cap Enforced by the Pool](#8-no-per-key-concurrency-cap-enforced-by-the-pool) | 🟡 Medium | `pool.py`, `scheduler/` |
| 9 | [PoolMetrics Is Not Thread/Coroutine Safe](#9-poolmetrics-is-not-threadcoroutine-safe) | 🟡 Medium | `metrics/pool_metrics.py` |
| 10 | [JSON Storage Has High I/O Amplification](#10-json-storage-has-high-io-amplification) | 🟡 Medium | `storage/json_storage.py` |
| 11 | [`.env` Keys Not Stripped of Whitespace](#11-env-keys-not-stripped-of-whitespace) | 🟡 Medium | `example.py` |
| 12 | [Hard-Coded `cooldown=60.0` in Lifecycle Hooks](#12-hard-coded-cooldown60-in-lifecycle-hooks) | 🟡 Medium | `example.py` |
| 13 | [Latency EMA Not Reset on Rate-Limit or Failure](#13-latency-ema-not-reset-on-rate-limit-or-failure) | 🟡 Medium | `key_state.py` |
| 14 | [RoundRobinScheduler Index Skips Under Contention](#14-roundrobinscheduler-index-skips-under-contention) | 🟡 Medium | `scheduler/round_robin.py` |
| 15 | [Client-Level Race Condition (Shared `api_key` Mutation)](#15-client-level-race-condition-shared-api_key-mutation) | 🔴 Critical | `example.py` |

---

## 1. Key Leak on Unhandled Exception Paths

**Severity:** 🔴 Critical  
**Files:** [`pool.py`](keymesh/pool/pool.py), [`sync_pool.py`](keymesh/pool/sync_pool.py), [`example.py`](example.py)

### Problem

In Approach 1 and Approach 2 of `example.py`, the `pool.acquire()` call happens before the `try` block. If an exception is raised **between `acquire()` and the try block start** (e.g., an exception in `with_options()`, a `KeyboardInterrupt`, or an OOM error), the key's `active_requests` counter is incremented but never decremented. The key is permanently "stuck" as active.

```python
# ❌ PROBLEMATIC: key is acquired outside try/finally
key = pool.acquire()
start = time.monotonic()
try:
    scoped_client = sync_client.with_options(api_key=key)
    response = scoped_client.chat.completions.create(...)
    pool.release(key, latency=time.monotonic() - start)
except Exception as e:
    pool.mark_failed(key)   # ← only runs for Exception, not BaseException
```

**Specific leaks:**
- `KeyboardInterrupt` is a `BaseException`, not `Exception` — the `except Exception` block is skipped entirely, and the key is never released.
- Any exception raised in `scoped_client = sync_client.with_options(api_key=key)` before entering the `try` body will also skip cleanup because the acquire already fired.

### Solution

Always acquire inside a `try/finally` or use the lifecycle context manager pattern (Approach 3). Catch `BaseException` in the lifecycle hook to handle `KeyboardInterrupt` and `SystemExit`:

```python
@contextlib.asynccontextmanager
async def async_key_lifecycle(pool: KeyPool):
    key = await pool.acquire()
    start = time.monotonic()
    try:
        yield key
        await pool.release(key, latency=time.monotonic() - start)
    except RateLimitError:
        await pool.mark_rate_limited(key, cooldown=60.0)
        raise
    except BaseException:  # ← catch BaseException, not just Exception
        await pool.mark_failed(key)
        raise
```

---

## 2. Race Window Between `_try_acquire` and `increment_active`

**Severity:** 🔴 Critical  
**Files:** [`pool.py` L113–L121](keymesh/pool/pool.py), [`key_state.py`](keymesh/state/key_state.py)

### Problem

In `KeyPool.acquire()`, there is a two-step, non-atomic operation:

```python
async def _try_acquire(self) -> KeyState | None:
    async with self._pool_lock:                          # ← Lock acquired here
        candidates = [ks for ks in self._states.values() if ks.is_available]
        return self._scheduler.select(candidates)        # ← Lock RELEASED after return

# Back in acquire():
key_state = await self._try_acquire()
if key_state is not None:
    await key_state.increment_active()                   # ← Mutation happens OUTSIDE pool_lock
```

Between `_try_acquire()` releasing `_pool_lock` and `increment_active()` being called, another coroutine can observe the same key as `is_available`, select it too, and both coroutines will increment `active_requests` — resulting in double-counting and potential over-scheduling of the same key.

### Solution

`increment_active()` must be called **inside** `_pool_lock` to make selection and activation atomic:

```python
async def _try_acquire(self) -> KeyState | None:
    async with self._pool_lock:
        candidates = [ks for ks in self._states.values() if ks.is_available]
        key_state = self._scheduler.select(candidates)
        if key_state is not None:
            await key_state.increment_active()  # ← Atomically activate under the pool lock
        return key_state
```

Then remove the standalone `increment_active()` call in `acquire()`.

---

## 3. Deprecated `get_event_loop()` in `acquire()`

**Severity:** 🟠 High  
**File:** [`pool.py` L113](keymesh/pool/pool.py)

### Problem

`asyncio.get_event_loop()` is deprecated since Python 3.10 and raises a `DeprecationWarning` (or will emit errors in future Python versions) when called outside of a running event loop. The current code uses it for the deadline:

```python
deadline = asyncio.get_event_loop().time() + self._acquire_timeout
```

In Python 3.10+, the correct API inside a coroutine is `asyncio.get_running_loop()`.

### Solution

```python
# ✅ Use get_running_loop() which is always safe inside a coroutine
deadline = asyncio.get_running_loop().time() + self._acquire_timeout
# ...
remaining = deadline - asyncio.get_running_loop().time()
```

---

## 4. Exhausted Keys Are Never Re-admitted

**Severity:** 🟠 High  
**Files:** [`key_state.py`](keymesh/state/key_state.py), [`pool.py`](keymesh/pool/pool.py)

### Problem

Once a key's `failure_count >= max_failures`, `is_exhausted` returns `True` and `is_available` returns `False`. The key is excluded from scheduling permanently for the lifetime of the pool. There is no recovery mechanism.

In real-world systems, a key may:
- Temporarily lose connectivity (network blip → recovers in minutes)
- Hit provider-side server errors (5xx) that self-resolve
- Be rotated by the user and the same string is re-added

A permanent ban with no reset path means your pool degrades over time in any sustained high-error-rate scenario.

### Solution

Add a `reset_failures()` call inside `apply_cooldown()` — after a key is rate-limited and comes back, its consecutive failure counter should reset (it's healthy enough to accept new requests again):

```python
async def apply_cooldown(self, duration: float = 60.0) -> None:
    async with self._lock:
        self.cooldown_until = time.monotonic() + duration
        self.active_requests = max(0, self.active_requests - 1)
        self.failure_count = 0  # ← Reset on rate-limit: key is still valid, just throttled
```

Additionally, add an `add_key()` method to `KeyPool` so users can re-inject a refreshed key at runtime without restarting the pool:

```python
async def add_key(self, key: str) -> None:
    """Add or reset a key in the pool at runtime."""
    async with self._pool_lock:
        self._states[key] = KeyState(key=key, max_failures=self._max_failures)
```

---

## 5. Cooldown Manager Mutates State Without Lock

**Severity:** 🟠 High  
**File:** [`cooldown/manager.py` L30](keymesh/cooldown/manager.py)

### Problem

`CooldownManager.apply()` directly mutates `key_state.cooldown_until` without acquiring the key's internal `asyncio.Lock`:

```python
@staticmethod
def apply(key_state: "KeyState", duration: float = 60.0) -> None:
    key_state.cooldown_until = time.monotonic() + duration  # ← No lock!
```

If this method is called from `pool.py` while another coroutine is inside the `async with self._lock` block of `key_state`, a data race occurs on the `cooldown_until` field. Though Python's GIL protects simple attribute assignment at the interpreter level, the real danger is the semantic race: another task reads `is_cooling_down` between the moment the manager writes and before the state's own `apply_cooldown` method runs.

The docstring itself says "Prefer `key_state.apply_cooldown()` in async context" — meaning this method is dangerous and should not be called in async code at all.

### Solution

Either remove the `CooldownManager.apply()` static method entirely (since `KeyState.apply_cooldown()` is the correct path), or guard it with a clear deprecation warning:

```python
@staticmethod
def apply(key_state: "KeyState", duration: float = 60.0) -> None:
    """
    .. deprecated::
        Use ``await key_state.apply_cooldown(duration)`` in async contexts.
        This method is unsafe under concurrency and exists only for sync
        internal bootstrapping.
    """
    import warnings
    warnings.warn(
        "CooldownManager.apply() is not concurrency-safe. "
        "Use key_state.apply_cooldown() in async code.",
        DeprecationWarning,
        stacklevel=2,
    )
    key_state.cooldown_until = time.monotonic() + duration
```

---

## 6. JSON Storage Writes Raw API Keys to Disk

**Severity:** 🟠 High  
**File:** [`storage/json_storage.py`](keymesh/storage/json_storage.py)

### Problem

`JSONStorage.save()` persists the full state dict to disk. The key passed to `save()` is the **raw API key string** (e.g., `sk-proj-...`) used as the dictionary key:

```python
async def save(self, key: str, state: dict[str, Any]) -> None:
    async with self._lock:
        data = await self._read()
        data[key] = state   # ← "key" is the raw API key string!
        await self._write(data)
```

The resulting JSON file looks like:
```json
{
  "sk-proj-REAL_SECRET_KEY_HERE": {
    "key_suffix": "...ABCDEF",
    ...
  }
}
```

This writes **plaintext secrets to disk**, which is a serious security vulnerability in any shared or cloud environment (leaked in backups, logs, container snapshots, CI artifacts, etc).

### Solution

Hash the key before using it as the storage key. Use a stable, non-reversible hash (e.g., SHA-256):

```python
import hashlib

def _key_id(self, key: str) -> str:
    """Derive a stable, non-reversible storage identifier from the raw key."""
    return hashlib.sha256(key.encode()).hexdigest()[:16]

async def save(self, key: str, state: dict[str, Any]) -> None:
    async with self._lock:
        data = await self._read()
        data[self._key_id(key)] = state   # ← Store under hash, not raw key
        await self._write(data)
```

Note: since the `key_suffix` field in `snapshot()` already redacts the key (only last 6 chars), the `state` dict itself is safe. Only the top-level key in the JSON file needs to be hashed.

---

## 7. SemaphoreGroup Creates Semaphores in Wrong Event Loop

**Severity:** 🟠 High  
**File:** [`concurrency/semaphores.py`](keymesh/concurrency/semaphores.py)

### Problem

`SemaphoreGroup` uses a `defaultdict` with a lambda that creates `asyncio.Semaphore` objects on first access:

```python
self._sems: dict[str, asyncio.Semaphore] = defaultdict(
    lambda: asyncio.Semaphore(self._max)
)
```

In Python 3.10+, `asyncio.Semaphore()` created outside of a running event loop will bind itself to a deprecated/default loop. If the `SemaphoreGroup` is instantiated at module level (common in real applications), or in a context where no loop is running, the semaphores are bound to the wrong (or a disposed) loop. When later used inside `asyncio.run()`, the resulting `RuntimeError: This event loop is already running` or `got Future attached to a different loop` error is extremely hard to debug.

### Solution

Defer semaphore creation to first use inside the running loop. The `defaultdict` approach is the problem; replace it with a guarded factory:

```python
class SemaphoreGroup:
    def __init__(self, max_concurrent: int = 10) -> None:
        self._max = max_concurrent
        self._sems: dict[str, asyncio.Semaphore] = {}

    def acquire(self, key: str) -> asyncio.Semaphore:
        """Return (or lazily create) the semaphore for `key`."""
        if key not in self._sems:
            # Created inside a coroutine, so the running loop is guaranteed.
            self._sems[key] = asyncio.Semaphore(self._max)
        return self._sems[key]
```

This is safe as long as `acquire()` is called only from within a running async context (which is the documented usage pattern).

---

## 8. No Per-Key Concurrency Cap Enforced by the Pool

**Severity:** 🟡 Medium  
**Files:** [`pool.py`](keymesh/pool/pool.py), [`scheduler/`](keymesh/scheduler/)

### Problem

`KeyPool` tracks `active_requests` on each key, and the `LeastBusyScheduler` considers it for selection, but the pool **never enforces a hard cap** on how many concurrent requests a single key can handle. There is no `max_concurrent_per_key` parameter.

In real usage, many LLM providers (e.g., OpenAI) impose per-key **RPM (requests per minute)** and **TPM (tokens per minute)** hard limits that cause 429s if exceeded. Without a cap, a single key with many active requests will keep being selected by `LEAST_BUSY` while all others are cooling down, which will immediately trigger a second rate limit.

### Solution

Add an optional `max_concurrent` parameter to `KeyPool.__init__()` and filter candidates in `_try_acquire()`:

```python
class KeyPool:
    def __init__(
        self,
        keys: Sequence[str],
        *,
        max_concurrent_per_key: int | None = None,
        ...
    ) -> None:
        self._max_concurrent = max_concurrent_per_key
        ...

    async def _try_acquire(self) -> KeyState | None:
        async with self._pool_lock:
            candidates = [
                ks for ks in self._states.values()
                if ks.is_available
                and (
                    self._max_concurrent is None
                    or ks.active_requests < self._max_concurrent
                )
            ]
            ...
```

---

## 9. PoolMetrics Is Not Thread/Coroutine Safe

**Severity:** 🟡 Medium  
**File:** [`metrics/pool_metrics.py`](keymesh/metrics/pool_metrics.py)

### Problem

`PoolMetrics` uses plain integer counters (e.g., `self.total_acquires += 1`) with no locking. In Python, `int += 1` is **not atomic** at the bytecode level — it compiles to separate `LOAD_ATTR`, `BINARY_ADD`, and `STORE_ATTR` operations. Under `asyncio`, a coroutine switch can happen between these operations, causing lost increments in high-throughput scenarios.

While Python's GIL prevents true simultaneous execution in CPython, under `asyncio` this is still a correctness issue if a coroutine switch occurs mid-increment (which can happen with `asyncio.TaskGroup` or high fan-out scenarios).

### Solution

Use `threading.Lock` (for sync) or an `asyncio.Lock` (for async) to protect counter mutations, or use Python's `threading.local()` approach if granular accuracy is required. For a simpler solution, use `collections.Counter` with atomic operations, or just accept that metrics are approximate (document it clearly):

```python
# Simplest fix: document approximate semantics explicitly
class PoolMetrics:
    """
    Aggregated runtime metrics. Counters are best-effort approximate values
    under high concurrency — they do not use locks for performance.
    """
    ...
```

Or for strict accuracy:

```python
import threading

class PoolMetrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.total_acquires = 0
        ...

    def record_acquire(self) -> None:
        with self._lock:
            self.total_acquires += 1
```

---

## 10. JSON Storage Has High I/O Amplification

**Severity:** 🟡 Medium  
**File:** [`storage/json_storage.py`](keymesh/storage/json_storage.py)

### Problem

Every call to `save()` performs a full read–modify–write cycle of the **entire** JSON file:

```python
async def save(self, key: str, state: dict[str, Any]) -> None:
    async with self._lock:
        data = await self._read()   # ← Read entire file
        data[key] = state
        await self._write(data)     # ← Write entire file
```

In a pool of 50 keys with high concurrency (e.g., 200 req/s), this means 200 full JSON file reads + 200 full JSON file writes per second. The writes are serialized by `_lock`, creating a bottleneck. Under heavy load, the lock queue will grow indefinitely.

### Solution

**Short-term:** Keep an in-memory write-through cache and only flush to disk on a timer or on `close()`:

```python
class JSONStorage(BaseStorage):
    def __init__(self, path: str | Path = "keymesh_state.json", flush_interval: float = 5.0) -> None:
        self._path = Path(path)
        self._lock = asyncio.Lock()
        self._cache: dict[str, dict[str, Any]] = {}  # In-memory cache
        self._dirty = False

    async def save(self, key: str, state: dict[str, Any]) -> None:
        async with self._lock:
            self._cache[key] = state   # Write to cache only
            self._dirty = True

    async def close(self) -> None:
        """Flush pending writes on close."""
        if self._dirty:
            async with self._lock:
                await self._write(self._cache)
```

---

## 11. `.env` Keys Not Stripped of Whitespace

**Severity:** 🟡 Medium  
**File:** [`example.py` L16](example.py)

### Problem

API keys are loaded by splitting the env variable on commas:

```python
API_KEYS = os.getenv("OPENAI_API_KEYS", "").split(",")
```

If the `.env` file contains spaces after commas (e.g., `sk-key1, sk-key2, sk-key3`), each key will have a leading space (`" sk-key2"`). This causes 401 Unauthorized errors that are extremely confusing to debug since the key *looks* correct when printed.

Additionally, if `OPENAI_API_KEYS` is unset, the result is `[""]` — a list with one empty string — which passes the `if not keys` guard in `KeyPool.__init__()` and creates a `KeyState` with `key=""`. Every request will then fail with an authentication error.

### Solution

```python
raw = os.getenv("OPENAI_API_KEYS", "")
API_KEYS = [k.strip() for k in raw.split(",") if k.strip()]

if not API_KEYS:
    raise RuntimeError(
        "OPENAI_API_KEYS is not set or empty. "
        "Add at least one key to your .env file."
    )
```

---

## 12. Hard-Coded `cooldown=60.0` in Lifecycle Hooks

**Severity:** 🟡 Medium  
**File:** [`example.py` L109, L124](example.py)

### Problem

The lifecycle context managers hard-code a `cooldown=60.0` second cooldown on rate limits:

```python
except RateLimitError:
    pool.mark_rate_limited(key, cooldown=60.0)
```

In real usage, OpenAI's 429 response includes a `Retry-After` header with the exact cooldown duration. Ignoring this header and defaulting to 60 seconds means either:
- Waiting too long on a short cooldown (wasted capacity)
- Not waiting long enough on a long cooldown (immediately re-triggering a 429)

### Solution

Parse the `Retry-After` header from the exception when available:

```python
except RateLimitError as e:
    # Respect Retry-After if the provider includes it
    retry_after = 60.0
    if hasattr(e, 'response') and e.response is not None:
        retry_after_header = e.response.headers.get("retry-after")
        if retry_after_header:
            try:
                retry_after = float(retry_after_header)
            except ValueError:
                pass
    await pool.mark_rate_limited(key, cooldown=retry_after)
    raise
```

---

## 13. Latency EMA Not Reset on Rate-Limit or Failure

**Severity:** 🟡 Medium  
**File:** [`key_state.py` L90–L104](keymesh/state/key_state.py)

### Problem

`latency_avg` uses an EMA that only updates on `record_success()`. When a key is consistently failing or in cooldown for minutes, its `latency_avg` reflects a stale historical average from before the failure streak. When the key recovers, the `WeightedScheduler` gives it a weight based on this stale latency, which may be artificially low (fast) or artificially high (slow) — both mislead the scheduler.

In the `WeightedScheduler`, a key with `latency_avg=0.0` (never had a success) gets `latency_factor = 1.0 / (1 + 0.0) = 1.0`, giving it the maximum possible latency factor — making a brand-new key look deceptively "fast" and granting it disproportionate scheduling weight.

### Solution

After a cooldown recovery, decay the EMA toward a neutral value. Also initialize `latency_avg` to a sentinel that the scheduler can distinguish from "known fast":

```python
# In key_state.py:
INITIAL_LATENCY_ESTIMATE: float = 1.0  # Assume 1s until proven otherwise

@dataclass
class KeyState:
    latency_avg: float = field(default=INITIAL_LATENCY_ESTIMATE, init=False)
    ...
```

This way, new or recovering keys don't get a spurious "zero latency" boost.

---

## 14. RoundRobinScheduler Index Skips Under Contention

**Severity:** 🟡 Medium  
**File:** [`scheduler/round_robin.py`](keymesh/scheduler/round_robin.py)

### Problem

`RoundRobinScheduler` maintains a global `_index` counter. The `candidates` list passed to `select()` is pre-filtered (only available keys), so its length varies call-to-call as keys enter and leave cooldown. The modulo `self._index % len(candidates)` maps to a position in the *current available subset*, not the *original key list*:

```python
idx = self._index % len(candidates)
self._index = (self._index + 1) % len(candidates)
```

When `len(candidates)` changes between calls (say, from 3 to 2 as a key goes into cooldown), the `_index % len` calculation can land on an entirely different key than intended. The round-robin guarantee breaks completely — some keys will be selected repeatedly and others skipped for long stretches.

### Solution

The counter should cycle over the **total key count**, not the candidate count. Match the candidate after modulo against the full key list:

```python
class RoundRobinScheduler(BaseScheduler):
    def select(self, candidates: Sequence[KeyState]) -> KeyState | None:
        if not candidates:
            return None
        # Use total key list length externally — or simply rotate on candidates as-is
        # The simplest correct approach: rotate the candidates list by the counter
        with self._lock:
            n = len(candidates)
            idx = self._index % n
            self._index += 1   # Unbounded counter; modulo applied at read-time
        return candidates[idx]
```

Even better: have the scheduler receive all key states (not just available ones) from the pool, and skip unavailable ones while maintaining true positional rotation.

---

## 15. Client-Level Race Condition (Shared `api_key` Mutation)

**Severity:** 🔴 Critical  
**File:** [`example.py`](example.py)

### Problem

This problem is already documented in the existing `problem.md`, but it's worth restating succinctly for completeness: mutating a shared client's `api_key` attribute directly (e.g., `client.api_key = key`) across concurrent async tasks causes a classic read-modify-write race condition. Both tasks end up sending their request under whichever key was written last.

The `example.py` correctly avoids this with `with_options()` — but any user who reads the GEMINI.md `Pattern 2: extra_headers` example and then looks at their own existing codebase may still have this bug lurking.

### Solution

This is fully solved by the three patterns shown in `example.py`. Always use one of:
1. `client.with_options(api_key=key)` — safest, shares connection pool
2. `extra_headers={"Authorization": f"Bearer {key}"}` — per-request header injection
3. The lifecycle context manager — encapsulates the full acquire → call → release flow

Never do:
```python
# ❌ NEVER DO THIS — global mutation causes race conditions
client.api_key = key
response = await client.chat.completions.create(...)
```

---

## Summary Table

| # | Problem | Root Cause | Fix Complexity |
|---|---------|-----------|----------------|
| 1 | Key leak on unhandled exception | `BaseException` not caught | Low — catch `BaseException` |
| 2 | TOCTOU race: acquire vs. increment | Two-step non-atomic select+activate | Medium — move `increment_active` inside pool lock |
| 3 | Deprecated `get_event_loop()` | Python 3.10+ deprecation | Trivial — swap to `get_running_loop()` |
| 4 | Exhausted keys never recover | No re-admission path | Medium — add reset on cooldown + `add_key()` |
| 5 | CooldownManager bypasses lock | Direct field mutation | Low — deprecate or remove the method |
| 6 | Raw API keys written to disk | Key used as JSON dict key directly | Low — hash key before storing |
| 7 | SemaphoreGroup wrong event loop | `asyncio.Semaphore()` at instantiation time | Low — defer creation to first use |
| 8 | No per-key concurrency cap | No `max_concurrent_per_key` param | Medium — add param + filter in `_try_acquire` |
| 9 | PoolMetrics not thread-safe | No lock on counters | Low — add lock or document as approximate |
| 10 | JSON storage I/O amplification | Full read-write per save | Medium — add in-memory write-through cache |
| 11 | Keys not stripped of whitespace | `split(",")` without `.strip()` | Trivial — add strip + empty guard |
| 12 | Hard-coded cooldown ignores headers | No `Retry-After` header parsing | Low — parse `Retry-After` from exception |
| 13 | Stale latency EMA after recovery | EMA never resets or bootstraps | Low — set initial estimate to non-zero |
| 14 | RoundRobin breaks on filtered candidates | Modulo on candidate count, not total | Medium — unbounded counter + correct modulo |
| 15 | Shared `api_key` race condition | Direct global client mutation | Low — documented; use `with_options()` |
