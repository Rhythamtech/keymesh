"""
JSON file storage backend for synchronous contexts.

Persists key state to a local JSON file.
No external dependencies. Works in environments without SQLite or Redis.
"""

import hashlib
import json
import os
import threading
from pathlib import Path
from typing import Any, cast

from keymesh.storage.sync_base import BaseSyncStorage


class SyncJSONStorage(BaseSyncStorage):
    """
    Persistent storage backend using a local JSON file in a synchronous/threaded context.

    Writes are atomic: data is written to a temp file then renamed,
    preventing corruption on crash mid-write.
    """

    def __init__(self, path: str | Path = "keymesh_sync_state.json") -> None:
        self._path = Path(path)
        self._lock = threading.Lock()

    def _key_id(self, key: str) -> str:
        """Derive a stable, non-reversible storage identifier from the raw key."""
        return hashlib.sha256(key.encode()).hexdigest()[:16]

    def _read(self) -> dict[str, dict[str, Any]]:
        if not self._path.exists():
            return {}
        try:
            return cast(
                dict[str, dict[str, Any]],
                json.loads(self._path.read_text(encoding="utf-8")),
            )
        except (json.JSONDecodeError, OSError):
            return {}

    def _write(self, data: dict[str, dict[str, Any]]) -> None:
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(tmp, self._path)

    def save(self, key: str, state: dict[str, Any]) -> None:
        with self._lock:
            data = self._read()
            data[self._key_id(key)] = state  # store under hash, not raw key
            self._write(data)

    def load(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            data = self._read()
            return data.get(self._key_id(key))

    def load_all(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return self._read()

    def delete(self, key: str) -> None:
        with self._lock:
            data = self._read()
            data.pop(self._key_id(key), None)
            self._write(data)

    def close(self) -> None:
        """No-op for JSON backend."""
