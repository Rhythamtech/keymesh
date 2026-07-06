# KeyMesh

A transparent API key pool manager for the OpenAI SDK (and any `httpx`-based client). KeyMesh rotates keys across a pool, tracks per-key RPM windows, applies cooldowns on `429` responses, and retries automatically — without the caller needing to know.

---

## Installation

KeyMesh is distributed as a Python package managed with [uv](https://github.com/astral-sh/uv).

### Core (SQLite backend only)

```bash
uv add keymesh
# or
pip install keymesh
```

### With Redis backend

```bash
uv add "keymesh[redis]"
```

### With PostgreSQL backend

```bash
uv add "keymesh[postgres]"
```

### With all backends

```bash
uv add "keymesh[all]"
```

---

## Quick Start

```python
from keymesh import KeyMeshSyncHTTPClient
from openai import OpenAI

http_client = KeyMeshSyncHTTPClient(
    keys=["sk-key-one", "sk-key-two", "sk-key-three"],
)

client = OpenAI(
    api_key="placeholder",      # KeyMesh injects the real key per-request
    http_client=http_client,
    max_retries=0,              # Let KeyMesh handle retries
)

response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Hello!"}],
)
print(response.choices[0].message.content)
```

---

## Memory Backends

KeyMesh stores key state (RPM counters, cooldowns, leases) in a pluggable **memory backend**. Three backends are available.

### SQLite (default)

No extra dependencies. Uses an in-memory SQLite database by default.

```python
from keymesh import SqliteMemory, KeyMeshSyncHTTPClient

# In-memory (default) — state is lost when the process exits
memory = SqliteMemory()

# Persistent file — state survives restarts
memory = SqliteMemory(db_path="keymesh.db")

client = KeyMeshSyncHTTPClient(keys=["sk-..."], memory=memory)
```

**Constructor parameters**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `db_path` | `str` | `":memory:"` | SQLite path or URI. Use `":memory:"` for in-memory, or a file path for persistence. |
| `**kwargs` | | | Forwarded to `sqlite3.connect()`. |

---

### Redis

Requires `keymesh[redis]`. Uses a distributed Redis lock (`keymesh:lock`) to coordinate concurrent processes.

```python
from keymesh import RedisMemory, KeyMeshSyncHTTPClient

# Connect via URL
memory = RedisMemory(url="redis://localhost:6379/0")

# Or via individual parameters
memory = RedisMemory(host="localhost", port=6379, db=0, password="secret")

client = KeyMeshSyncHTTPClient(keys=["sk-..."], memory=memory)
```

**Constructor parameters**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `url` | `str \| None` | `None` | Redis URL. Takes precedence over individual params when set. |
| `host` | `str` | `"localhost"` | Redis host. |
| `port` | `int` | `6379` | Redis port. |
| `db` | `int` | `0` | Redis database index. |
| `password` | `str \| None` | `None` | Redis password. |
| `**kwargs` | | | Forwarded to `redis.from_url()` or `redis.Redis()`. Useful for `socket_timeout`, `socket_connect_timeout`, etc. |

**Extra method**

```python
memory.flush_all()   # Deletes all keymesh:* keys from Redis
```

---

### PostgreSQL

Requires `keymesh[postgres]`. Uses table-level `EXCLUSIVE` locks to coordinate concurrent processes.

```python
from keymesh import PostgresMemory, KeyMeshSyncHTTPClient

memory = PostgresMemory(
    conninfo="postgresql://postgres:postgres@localhost:5432/keymesh"
)

client = KeyMeshSyncHTTPClient(keys=["sk-..."], memory=memory)

# Always close the connection when done
memory.close()
```

**Constructor parameters**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `conninfo` | `str` | `"postgresql://postgres:postgres@localhost:5432/keymesh"` | PostgreSQL connection string. |
| `**kwargs` | | | Forwarded to `psycopg.connect()`. Useful for `connect_timeout`, etc. |

**Extra method**

```python
memory.close()   # Closes the underlying psycopg connection
```

---

## `KeyMeshSyncHTTPClient`

A drop-in subclass of `httpx.Client`. Intercepts every request to inject the best available key, retries on `429`, and applies cooldowns transparently.

```python
from keymesh import KeyMeshSyncHTTPClient, SqliteMemory

client = KeyMeshSyncHTTPClient(
    keys=["sk-one", "sk-two"],
    memory=SqliteMemory(),           # optional, defaults to in-memory SQLite
    max_retries_per_request=3,
    cooldown_seconds=60.0,
    window_seconds=60,
    default_rpm=60,
    debug_logging=False,
)
```

### Constructor parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `keys` | `list[str]` | required | List of raw API keys to pool. |
| `memory` | `Any \| None` | `None` | Memory backend instance. Defaults to `SqliteMemory(db_path=":keymesh:")`. |
| `db_path` | `str` | `":keymesh:"` | SQLite path used only when `memory` is `None`. |
| `max_retries_per_request` | `int` | `3` | Maximum retry attempts per outgoing request before raising. |
| `cooldown_seconds` | `float` | `60.0` | How long a key is placed in cooldown after a `429` response. |
| `window_seconds` | `int` | `60` | RPM window duration in seconds. |
| `default_rpm` | `int` | `60` | Default requests-per-minute limit assigned to each key. |
| `timeout` | `float \| None` | `None` | HTTP timeout passed to `httpx.Client`. |
| `debug_logging` | `bool` | `False` | Emit structured debug logs for request events. |
| `**kwargs` | | | Forwarded to `httpx.Client`. |

### Key selection strategy

On each request KeyMesh:
1. Queries all **non-disabled** keys from the memory backend.
2. Excludes keys whose `cooldown_until` is still in the future.
3. Resets the RPM window for keys whose `window_seconds` has elapsed.
4. Excludes keys at or above their `rpm` limit.
5. Sorts remaining candidates by `(request_count, last_used_at, window_start_at)` ascending — preferring the least-used, least-recently-used key.
6. Injects the chosen key's value into the `Authorization: Bearer <key>` header.
7. On `429`: puts the key into cooldown and retries with the next candidate.
8. On network error: releases the lease and retries.

---

## Data Models

```python
from keymesh.model import KeyConfig, KeyState, KeyLease
```

### `KeyConfig`

| Field | Type | Description |
|-------|------|-------------|
| `api_hash` | `str` | SHA-256 hash of the raw API key (used as the stable identifier). |
| `api_key` | `str` | The raw API key value. |
| `request_per_minute` | `int` | RPM limit for this key. |
| `is_disable` | `bool` | If `True`, the key is excluded from selection. |

### `KeyState`

| Field | Type | Description |
|-------|------|-------------|
| `api_hash` | `str` | References `KeyConfig.api_hash`. |
| `window_start_at` | `datetime` | When the current RPM window began. |
| `last_used_at` | `datetime \| None` | Timestamp of the most recent use. |
| `request_count` | `int` | Requests made in the current window. |
| `cooldown_until` | `datetime \| None` | Key is unavailable until this time. |
| `last_429_at` | `datetime \| None` | Timestamp of the last 429 received. |

### `KeyLease`

| Field | Type | Description |
|-------|------|-------------|
| `api_hash` | `str` | The key that was acquired. |
| `api_key` | `str` | The raw key value injected into the request. |
| `attempt` | `int` | Which retry attempt this lease belongs to. |
| `acquire_at` | `datetime` | When the lease was acquired. |
| `release_at` | `datetime` | When the lease was released. |

---

## Monitoring

Every memory backend exposes `fetch_db_stats()` for basic observability:

```python
stats = memory.fetch_db_stats()
# {
#   "total_keys":       2,
#   "active_leases":    1,
#   "keys_in_cooldown": 0,
#   "total_leases":     47,
#   "last_lease_time":  datetime(...)
# }
```

---

## Environment Variables

Copy `.env.example` to `.env` and populate as needed:

```dotenv
KEYMESH_POSTGRES_URL=postgresql://postgres:postgres@localhost:5432/keymesh
KEYMESH_REDIS_URL=redis://localhost:6379/0
KEYMESH_SQLITE_PATH=:memory:
```

Load them in your application with `python-dotenv`:

```python
from dotenv import load_dotenv
import os

load_dotenv()

from keymesh import PostgresMemory
memory = PostgresMemory(conninfo=os.environ["KEYMESH_POSTGRES_URL"])
```

