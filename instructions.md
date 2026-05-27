# Development Instructions — KeyMesh

# Primary Rule

KeyMesh is a:
- credential orchestration runtime
- key pool manager
- API credential scheduler

KeyMesh is NOT:
- an SDK wrapper
- a proxy
- an HTTP gateway
- a transport framework

---

# Runtime Flow

```text
Application
    ↓
Existing SDK / HTTP Client
    ↓
KeyMesh Runtime
    ↓
Key Allocation
    ↓
Provider
```

---

# Core Responsibilities

KeyMesh should ONLY:
- allocate keys
- manage cooldowns
- track runtime state
- coordinate concurrency
- handle scheduling logic

---

# Forbidden Responsibilities

DO NOT:
- implement inference APIs
- create proxy servers
- wrap OpenAI SDK
- abstract provider requests
- format chat payloads

---

# Key API Design

Minimal public interface:

```python
key = await pool.acquire()
```

On success:

```python
await pool.release(key)
```

On failure:

```python
await pool.mark_failed(key)
```

Optional:

```python
await pool.mark_rate_limited(key)
```

---

# Scheduler Requirements

Implement:

## Round Robin

Sequential rotation.

---

## Least Busy

Prefer:
- lower active requests

---

## Weighted Routing

Prefer:
- healthier keys
- lower latency
- fewer failures

---

# Runtime State Tracking

Each key must track:

```python
{
    "active_requests": int,
    "cooldown_until": float,
    "success_count": int,
    "failure_count": int,
    "latency_avg": float,
    "last_used": float
}
```

---

# Concurrency Requirements

Must support:
- asyncio
- high concurrency
- multithreaded environments

Use:
- asyncio.Lock
- semaphores
- atomic updates

Avoid:
- race conditions
- global mutable state

---

# Cooldown Rules

On HTTP 429:
- mark key unavailable
- apply cooldown duration

Example:

```python
cooldown_until = now + 60
```

Unavailable keys must be skipped by scheduler.

---

# Retry Rules

On:
- timeout
- connection failure
- 429
- provider 5xx

System should:
1. mark failure
2. allocate another key
3. retry operation

---

# Persistence Layer

Optional backends:
- memory
- SQLite
- Redis
- JSON

Persistence stores:
- cooldown state
- metrics
- runtime statistics

---

# Internal Structure

```text
keymesh/
├── pool/
├── scheduler/
├── state/
├── cooldown/
├── concurrency/
├── metrics/
├── storage/
└── utils/
```

---

# Coding Standards

Required:
- type hints
- modular architecture
- strategy pattern
- async-safe design
- production-grade error handling

Avoid:
- tight coupling
- singleton architecture
- framework-specific logic

---

# Future-ready Design

Architecture should support:
- distributed scheduling
- adaptive learning
- ML-based routing
- token-aware balancing
- encrypted key vaults

without major rewrites.

---

# Final Goal

Build a:
- lightweight
- scalable
- concurrency-safe
- framework-agnostic

credential orchestration runtime for AI API systems.