# Project Prompt — KeyMesh

You are building a production-grade Python project called KeyMesh.

KeyMesh is a credential orchestration runtime for AI API systems.

It is NOT:
- an SDK wrapper
- an AI gateway
- a proxy server
- an inference framework

Instead, KeyMesh acts as:
- an API key allocator
- a concurrency-safe scheduler
- a rate-limit aware credential pool

---

# Main Objective

Allow ANY project to efficiently use multiple API keys together.

Example:

```text
3 API keys
10 RPM each

≈ 30 RPM total throughput
```

KeyMesh should intelligently distribute usage across available credentials.

---

# Important Architectural Constraint

KeyMesh MUST remain:

## Framework Agnostic

Must integrate into:
- OpenAI SDK
- Anthropic SDK
- requests
- httpx
- aiohttp
- LangChain
- CrewAI
- custom clients

without tightly coupling to any framework.

---

# Core Responsibilities

ONLY solve:
- credential allocation
- key state tracking
- rate-limit scheduling
- cooldown handling
- concurrency coordination

DO NOT solve:
- request formatting
- model APIs
- inference abstraction
- transport wrappers

---

# Public API

Expected usage:

```python
key = await pool.acquire()

headers = {
    "Authorization": f"Bearer {key}"
}
```

On success:

```python
await pool.release(key)
```

On failure:

```python
await pool.mark_failed(key)
```

---

# Runtime State

Each key maintains:

```python
{
    "active_requests": 0,
    "cooldown_until": 0,
    "failure_count": 0,
    "success_count": 0,
    "latency_avg": 0
}
```

---

# Scheduling Strategies

Implement:
- round robin
- least busy
- weighted routing

Architecture must support future:
- adaptive learning
- token-aware balancing
- intelligent routing

---

# Retry Rules

Retry on:
- 429
- timeout
- connection failure
- provider 5xx

On 429:
- cooldown key
- retry with alternative credential

---

# Technical Requirements

Use:
- Python 3.11+
- asyncio
- lightweight architecture
- concurrency-safe design

Avoid:
- FastAPI
- Flask
- proxy servers
- Docker dependency
- middleware runtimes

---

# Persistence

Optional persistence:
- memory
- SQLite
- Redis
- JSON

---

# Project Philosophy

KeyMesh is:
- infrastructure
- runtime orchestration
- credential scheduling

NOT:
- model abstraction
- inference layer
- gateway proxy
- observability platform