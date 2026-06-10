# 🗝️ KeyMesh

**Lightweight, concurrency-safe credential orchestration for AI API systems.**

[![PyPI version](https://img.shields.io/badge/python-3.12+-blue.svg)](https://pyproject.toml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Tool: uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)

KeyMesh is a high-performance runtime designed to multiplex multiple API keys (e.g., OpenAI, Anthropic, Gemini) across highly concurrent workloads. It maximizes aggregate throughput by managing rate limits, cooldowns, and scheduling strategies without being tied to any specific LLM provider or SDK.

---

## ✨ Features

- **🚀 Maximized Throughput:** Pool multiple lower-tier keys to behave as a single high-tier endpoint.
- **🛡️ Concurrency Safe:** Native `asyncio` and multi-threaded synchronous support with granular locks for high-frequency safe acquisition.
- **🔌 Sync & Async Native:** Identical features available in both async-first runtimes and standard synchronous/threaded architectures.
- **🔄 Pluggable Schedulers:** Choose between `RoundRobin`, `LeastBusy`, or `Weighted` strategies.
- **❄️ Smart Cooldowns:** Automatically skips rate-limited keys and reintroduces them after a configurable backoff.
- **📊 Health Monitoring:** Tracks latency (EMA), success rates, and consecutive failures to prune dead credentials.
- **💾 Flexible Storage:** Memory and JSON persistent backends for both async (`MemoryStorage`, `JSONStorage`) and sync (`SyncMemoryStorage`, `SyncJSONStorage`) runtimes.
- **🔌 Framework Agnostic:** Zero dependencies on `openai` or `anthropic` SDKs. Use it with any HTTP client.

---

## 📦 Installation

KeyMesh is optimized for the [uv](https://github.com/astral-sh/uv) package manager.

```bash
# Core package
uv add keymesh
pip install keymesh

# With OpenAI SDK integration support
uv add keymesh --optional openai
pip install keymesh[openai]
```


---

## 🚀 Quick Start

KeyMesh stays out of your network stack. You acquire a key, use it with your preferred SDK, and report the outcome. To ensure high-throughput and concurrency safety, initialize a single client and pass the acquired keys dynamically per request.

### ⚡ Asynchronous Example

```python
import asyncio
import time
from openai import AsyncOpenAI
from keymesh import KeyPool, SchedulerStrategy

# 1. Initialize a reusable LLM client once (reuses the TCP connection pool)
client = AsyncOpenAI()

async def make_request(pool: KeyPool):
    # 2. Acquire a key from the pool (non-blocking selection)
    key = await pool.acquire()
    
    start_time = time.monotonic()
    try:
        # 3. Create a request-scoped client with the acquired key
        scoped_client = client.with_options(api_key=key)
        response = await scoped_client.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": "Hello KeyMesh Async!"}]
        )
        # 4. Release key back to the pool on success with latency tracking
        await pool.release(key, latency=time.monotonic() - start_time)
        print(f"Response: {response.choices[0].message.content}")
        
    except Exception as e:
        # 5. Handle failures or rate limits
        if "rate_limit" in str(e).lower():
            await pool.mark_rate_limited(key, cooldown=60.0)
        else:
            await pool.mark_failed(key)

async def main():
    pool = KeyPool(
        keys=["sk-key-1", "sk-key-2", "sk-key-3"],
        strategy=SchedulerStrategy.LEAST_BUSY
    )
    try:
        await make_request(pool)
    finally:
        await pool.close()

asyncio.run(main())
```

### 🔌 Synchronous Example (Thread-Safe)

```python
import time
from openai import OpenAI
from keymesh import SyncKeyPool, SchedulerStrategy

# 1. Initialize a reusable LLM client once
client = OpenAI()

def make_request(pool: SyncKeyPool):
    # 2. Acquire a key synchronously (blocking/thread-safe)
    key = pool.acquire()
    
    start_time = time.monotonic()
    try:
        # 3. Create a request-scoped client with the acquired key
        scoped_client = client.with_options(api_key=key)
        response = scoped_client.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": "Hello KeyMesh Sync!"}]
        )
        # 4. Release key back to the pool on success with latency tracking
        pool.release(key, latency=time.monotonic() - start_time)
        print(f"Response: {response.choices[0].message.content}")
        
    except Exception as e:
        # 5. Handle failures or rate limits
        if "rate_limit" in str(e).lower():
            pool.mark_rate_limited(key, cooldown=60.0)
        else:
            pool.mark_failed(key)

def main():
    pool = SyncKeyPool(
        keys=["sk-key-1", "sk-key-2", "sk-key-3"],
        strategy=SchedulerStrategy.LEAST_BUSY
    )
    try:
        make_request(pool)
    finally:
        pool.close()

main()
```

---

## 🔑 Key Management Integration Patterns

When load-balancing API requests concurrently, **never** recreate the client on every request (which destroys the connection pool) and **never** mutate `client.api_key = key` globally (which causes race conditions across concurrent tasks).

Instead, use one of these concurrency-safe patterns:

### Pattern 1: Transparent HTTP Client Handlers (Recommended 🚀)
Pass the integration handler directly as the `http_client` parameter in the OpenAI SDK. KeyMesh will transparently acquire, release, rate-limit (detecting 429 and Retry-After), and track failure statistics under the hood without changing how you call the SDK.

```python
# Async Example
from openai import AsyncOpenAI
from keymesh import AsyncOpenAIHandler, SchedulerStrategy

handler = AsyncOpenAIHandler(
    keys=["sk-1", "sk-2", "sk-3"],
    strategy=SchedulerStrategy.ROUND_ROBIN,
)
client = AsyncOpenAI(api_key="dummy", http_client=handler)

# Use standard OpenAI SDK calls. KeyMesh operates completely transparently!
response = await client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Hello!"}]
)

# Sync Example
from openai import OpenAI
from keymesh import OpenAIHandler

handler = OpenAIHandler(keys=["sk-1", "sk-2", "sk-3"])
client = OpenAI(api_key="dummy", http_client=handler)
response = client.chat.completions.create(...)
```

### Pattern 2: Request-Scoped Client Overrides (`with_options`)

*Recommended for modern OpenAI SDKs.* Generates a copy of the client config pointing to the new key, while sharing the underlying connection pool.

```python
# Async
scoped_client = client.with_options(api_key=key)
response = await scoped_client.chat.completions.create(...)

# Sync
scoped_client = client.with_options(api_key=key)
response = scoped_client.chat.completions.create(...)
```

### Pattern 3: Per-Request Custom Headers (`extra_headers`)
Injects the authorization key directly inside the request header without changing client-wide configurations.

```python
# Async & Sync
response = await client.chat.completions.create(
    model="gpt-4",
    messages=[{"role": "user", "content": "Query"}],
    extra_headers={"Authorization": f"Bearer {key}"}
)
```

### Pattern 4: Automated Lifecycle Context Managers
Encapsulates acquiring, releasing, timing, and error state tracking into reusable Python context managers to prevent key leaks.

```python
import time
import contextlib

@contextlib.asynccontextmanager
async def key_lifecycle(pool: KeyPool):
    key = await pool.acquire()
    start = time.monotonic()
    try:
        yield key
        await pool.release(key, latency=time.monotonic() - start)
    except Exception:
        await pool.mark_failed(key)
        raise

# Usage
async with key_lifecycle(pool) as key:
    scoped_client = client.with_options(api_key=key)
    response = await scoped_client.chat.completions.create(...)
```

---

## 🛠️ Architecture

KeyMesh follows a modular, thread-safe, and async-safe design:

- **KeyPool / SyncKeyPool:** The central async / sync orchestrators.
- **Scheduler:** Stateless selection logic for choosing the next key (e.g. `RoundRobin`, `LeastBusy`, `Weighted`).
- **KeyState / SyncKeyState:** Thread-safe runtime metrics tracking per API key.
- **Storage / BaseSyncStorage:** Pluggable persistence layers (In-Memory or JSON-backed) for both asynchronous and synchronous runtimes.

---

## 🛠️ Development

This project uses `uv` for development.

```bash
# Install dependencies
uv sync

# Run tests
uv run pytest

# Lint and Format
uv run ruff check .
uv run mypy .
```

---

## 📄 License

MIT License. See [LICENSE](LICENSE) for details.
