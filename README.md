# 🗝️ KeyMesh

**Lightweight, concurrency-safe credential orchestration for AI API systems.**

[![PyPI version](https://img.shields.io/badge/python-3.12+-blue.svg)](https://pyproject.toml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Tool: uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)

KeyMesh is a high-performance, framework-agnostic runtime designed to multiplex multiple API keys (e.g., OpenAI, Anthropic, Gemini) across highly concurrent workloads. It maximizes aggregate throughput by managing rate limits, cooldowns, and scheduling strategies—acting purely as a routing scheduler and cooldown manager.

---

## ✨ Features

- **🚀 Maximized Throughput:** Pool multiple lower-tier keys to act as a single high-throughput endpoint.
- **🛡️ Concurrency Safe:** Native `asyncio` and multi-threaded synchronous support with granular locks for high-frequency safe acquisition.
- **🔌 Sync & Async Native:** Identical features available in both async-first runtimes and standard synchronous/threaded architectures.
- **🔄 Pluggable Schedulers:** Choose between `RoundRobin`, `LeastBusy`, or `Weighted` strategies.
- **❄️ Smart Cooldowns:** Automatically detects rate limits (`HTTP 429`), parses `Retry-After` headers, and temporarily cools down keys.
- **📊 Health Monitoring:** Tracks latency using Exponential Moving Average (EMA), success rates, and consecutive failures to prune dead credentials.
- **💾 Flexible Storage:** Memory and JSON persistent backends for both async (`MemoryStorage`, `JSONStorage`) and sync (`SyncMemoryStorage`, `SyncJSONStorage`) runtimes.
- **🔌 Zero Heavy Couplings:** No hard runtime dependencies on specific client SDKs. Integrates natively via HTTP client adapters.

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

## 🚀 Recommended Approach: Transparent HTTP Client Handlers

The easiest, most robust way to integrate KeyMesh with the OpenAI SDK is using the built-in [OpenAIHandler](file:///Users/rhythamnegi/Code/keymesh/keymesh/integrations/openai_handler.py) and [AsyncOpenAIHandler](file:///Users/rhythamnegi/Code/keymesh/keymesh/integrations/openai_handler.py). 

These handlers subclass `httpx.Client` and `httpx.AsyncClient` respectively. When passed directly into the OpenAI SDK client constructor as the `http_client`, they intercept outgoing requests transparently to:
1. **Acquire** a key from the pool automatically before the request starts.
2. **Inject** the key dynamically into the request's `Authorization` header.
3. **Measure** the latency of the request and record it on the key's stats upon success.
4. **Cool down** the key if the server returns `HTTP 429` (automatically parsing the `Retry-After` header if present).
5. **Prune / Mark Failed** the key if connection errors or exceptions occur during transmission.

> [!IMPORTANT]
> This approach keeps your code clean. You do not need to call `pool.acquire()`, `pool.release()`, or handle try/except blocks around key status updates manually. KeyMesh manages everything at the HTTP transport layer!

### ⚡ Asynchronous Integration (Recommended)

```python
import asyncio
from openai import AsyncOpenAI
from keymesh import AsyncOpenAIHandler, SchedulerStrategy

async def main():
    # 1. Initialize the AsyncOpenAIHandler with your keys
    handler = AsyncOpenAIHandler(
        keys=["sk-key-1", "sk-key-2", "sk-key-3"],
        strategy=SchedulerStrategy.LEAST_BUSY,
        default_cooldown=60.0
    )

    # 2. Pass the handler directly as the http_client to AsyncOpenAI
    client = AsyncOpenAI(
        api_key="dummy-key",  # The dummy value is overridden dynamically per-request
        http_client=handler
    )

    try:
        # 3. Call the SDK normally! Key rotation & state management is 100% transparent.
        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": "Hello KeyMesh Async!"}]
        )
        print(f"Response: {response.choices[0].message.content}")
    finally:
        # 4. Gracefully close the handler to persist metrics/storage
        await handler.aclose()

asyncio.run(main())
```

### 🔌 Synchronous Integration (Thread-Safe)

```python
from openai import OpenAI
from keymesh import OpenAIHandler, SchedulerStrategy

def main():
    # 1. Initialize the thread-safe OpenAIHandler
    handler = OpenAIHandler(
        keys=["sk-key-1", "sk-key-2", "sk-key-3"],
        strategy=SchedulerStrategy.ROUND_ROBIN
    )

    # 2. Pass the handler directly as the http_client to OpenAI
    client = OpenAI(
        api_key="dummy-key",
        http_client=handler
    )

    try:
        # 3. Use the SDK as usual
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": "Hello KeyMesh Sync!"}]
        )
        print(f"Response: {response.choices[0].message.content}")
    finally:
        # 4. Gracefully close the handler
        handler.close()

if __name__ == "__main__":
    main()
```

---

## 💡 Low-Level / Custom Integration Patterns

If you are using a custom HTTP client, a different LLM SDK (like Anthropic, Gemini, or Cohere), or need manual control over the lifecycle of your credentials, you can interface directly with [KeyPool](file:///Users/rhythamnegi/Code/keymesh/keymesh/pool/pool.py) or [SyncKeyPool](file:///Users/rhythamnegi/Code/keymesh/keymesh/pool/sync_pool.py).

> [!WARNING]
> **Strict Concurrency Rule:** Never mutate a shared client's API key globally (e.g. `client.api_key = key`) in concurrent loops as it causes race conditions. Instead, use one of the patterns below to scope the key to the request context.

### Pattern 1: Request-Scoped Client Overrides (`with_options`)
Modern SDKs support copying a client configuration with a overridden API key while sharing the underlying connection pool.

```python
# Async
key = await pool.acquire()
start = time.monotonic()
try:
    scoped_client = client.with_options(api_key=key)
    response = await scoped_client.chat.completions.create(...)
    await pool.release(key, latency=time.monotonic() - start)
except Exception:
    await pool.mark_failed(key)
    raise
```

### Pattern 2: Per-Request Custom Headers (`extra_headers`)
Pass the key as an HTTP header directly in the API call, bypassing global client state.

```python
key = await pool.acquire()
start = time.monotonic()
try:
    response = await client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": "Query"}],
        extra_headers={"Authorization": f"Bearer {key}"}
    )
    await pool.release(key, latency=time.monotonic() - start)
except Exception:
    await pool.mark_failed(key)
    raise
```

### Pattern 3: Context Managers (`key_lifecycle`)
Encapsulate the acquire/release/fail lifecycle into a clean Python context manager:

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

- **[KeyPool](file:///Users/rhythamnegi/Code/keymesh/keymesh/pool/pool.py) / [SyncKeyPool](file:///Users/rhythamnegi/Code/keymesh/keymesh/pool/sync_pool.py):** The central async / sync orchestrators.
- **[Scheduler](file:///Users/rhythamnegi/Code/keymesh/keymesh/scheduler/base.py):** Stateless selection logic for choosing the next key (e.g. `RoundRobin`, `LeastBusy`, `Weighted`).
- **[KeyState](file:///Users/rhythamnegi/Code/keymesh/keymesh/state/key_state.py) / [SyncKeyState](file:///Users/rhythamnegi/Code/keymesh/keymesh/state/sync_key_state.py):** Lock-guarded runtime diagnostics tracking per API key (failures, latency average, cooldown timers, active requests).
- **[Storage](file:///Users/rhythamnegi/Code/keymesh/keymesh/storage/base.py):** Pluggable persistence layers (In-Memory or JSON-backed) for both asynchronous and synchronous runtimes.

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

