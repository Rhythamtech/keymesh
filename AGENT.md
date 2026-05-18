# KeyMesh Agent Instruction & Development Runbook

This document is the official instruction set and runbook for **AI Coding Agents** operating in the KeyMesh repository. All modifications, refactorings, and pull requests must adhere to the rules specified here.

---

## 🎯 Primary Agent Mandate

You are tasked with maintaining a production-grade, highly performant, async-safe Python codebase. **KeyMesh** must remain lightweight and zero-dependency (outside of optional async DB drivers/caches).

> [!WARNING]
> **Strict Limits on Scope & Dependencies:**
> - **DO NOT** add or import high-overhead frameworks like FastAPI, Flask, or Django.
> - **DO NOT** try to wrap model APIs or implement chat-payload formatters.
> - **DO NOT** use global mutable states or create tight couplings to third-party SDKs.
> - **DO NOT** implement proxy servers or HTTP middleware layers inside KeyMesh.

---

## 🛠️ Tooling & Workspace Standards

We use **`uv`** as the default package and project manager. Always configure custom writable cache paths when invoking `uv` commands in restricted environments to avoid directory permissions issues.

### Cache Directory Override:
```bash
mkdir -p ~/.uv_cache
export UV_CACHE_DIR=~/.uv_cache
```

### Useful CLI Commands for Agents:
- **Run the test suite:**
  ```bash
  python -m pytest tests/ -v
  ```
- **Execute type checking & static analysis:**
  ```bash
  mypy keymesh/
  ruff check keymesh/
  ```
- **Execute runtime demo:**
  ```bash
  python main.py
  ```

---

## 🧬 Coding Guidelines & Code Style

Agents must produce pristine code conforming to the following standards:

1. **Type Annotation**: Every single function parameter, return value, and class field must be fully typed. Use strict `mypy` style annotations.
2. **Concurrency Patterns**:
   - Mutate shared state safely using `asyncio.Lock`.
   - Protect global/pool-level operations using `self._pool_lock`.
   - Prefer thread-safe atomics or thread locks (`threading.Lock`) for synchronous shared resources (e.g. `RoundRobinScheduler._index`).
3. **Graceful Error Handling**:
   - Never let internal exceptions leak directly without being wrapped in subclasses of `KeyMeshError`.
   - Handle edge-cases such as empty pools, all keys rate-limited, and key exhaustion cleanly.
4. **EMA Calculations**:
   - Key latencies must be smoothed using Exponential Moving Average (EMA) with an default alpha of `0.2` to avoid heavy volatility from individual network hiccups:
     $$\text{Latency}_{\text{avg}} = \alpha \cdot \text{Latency}_{\text{new}} + (1 - \alpha) \cdot \text{Latency}_{\text{prev}}$$

---

## 🧪 Test Requirements

- Every new scheduler, persistence backend, or concurrency utility must be accompanied by comprehensive tests under `tests/`.
- Tests must use `pytest-asyncio` with `asyncio_mode = "auto"`.
- Test suites must verify:
  - Behavior under high concurrency (multiple simultaneous acquisitions).
  - Recovery from failure states (exhaustion and cooldown expiry).
  - Expected distribution rates for scheduling strategies.
