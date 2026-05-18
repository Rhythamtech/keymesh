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
# Using uv
uv add keymesh

# Standard pip
pip install keymesh
```

---

## 🚀 Quick Start

KeyMesh stays out of your network stack. You acquire a key, use it with your preferred SDK, and report the outcome.

### ⚡ Asynchronous Example

```python
import asyncio
from openai import AsyncOpenAI
from keymesh import KeyPool, SchedulerStrategy

async def main():
    # 1. Initialize the pool with multiple keys
    pool = KeyPool(
        keys=["sk-key-1", "sk-key-2", "sk-key-3"],
        strategy=SchedulerStrategy.LEAST_BUSY
    )

    # 2. Acquire a credential (non-blocking scheduler selection)
    key = await pool.acquire()
    
    # 3. Use the key with the OpenAI client directly
    client = AsyncOpenAI(api_key=key)
    
    try:
        start_time = asyncio.get_event_loop().time()
        response = await client.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": "Hello KeyMesh Async!"}]
        )
        latency = asyncio.get_event_loop().time() - start_time
        
        # 4. Release key back to the pool on success
        await pool.release(key, latency=latency)
        print(f"Response: {response.choices[0].message.content}")
        
    except Exception as e:
        # 5. Handle failures or rate limits
        if "rate_limit" in str(e).lower():
            await pool.mark_rate_limited(key, cooldown=60.0)
        else:
            await pool.mark_failed(key)

asyncio.run(main())
```

### 🔌 Synchronous Example (Thread-Safe)

```python
import time
from openai import OpenAI
from keymesh import SyncKeyPool, SchedulerStrategy

def main():
    # 1. Initialize the thread-safe pool
    pool = SyncKeyPool(
        keys=["sk-key-1", "sk-key-2", "sk-key-3"],
        strategy=SchedulerStrategy.LEAST_BUSY
    )

    # 2. Acquire a credential synchronously (blocking/thread-safe)
    key = pool.acquire()
    
    # 3. Use the key with the synchronous OpenAI client directly
    client = OpenAI(api_key=key)
    
    try:
        start_time = time.monotonic()
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": "Hello KeyMesh Sync!"}]
        )
        latency = time.monotonic() - start_time
        
        # 4. Release key back to the pool on success
        pool.release(key, latency=latency)
        print(f"Response: {response.choices[0].message.content}")
        
    except Exception as e:
        # 5. Handle failures or rate limits
        if "rate_limit" in str(e).lower():
            pool.mark_rate_limited(key, cooldown=60.0)
        else:
            pool.mark_failed(key)

main()
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
