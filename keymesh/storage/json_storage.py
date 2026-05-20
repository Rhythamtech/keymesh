"""
JSON file storage backend.

Persists key state to a local JSON file.
No external dependencies. Works in environments without SQLite or Redis.
"""

import asyncio
import hashlib
import json
import os
from pathlib import Path
from typing import Any, cast

from keymesh.storage.base import BaseStorage


class JSONStorage(BaseStorage):
    """
    Persistent storage backend using a local JSON file.

    Writes are atomic: data is written to a temp file then renamed,
    preventing corruption on crash mid-write.
    """

    def __init__(self, path: str | Path = "keymesh_state.json") -> None:
        self._path = Path(path)
        self._lock = asyncio.Lock()

    def _key_id(self, key: str) -> str:
        """Derive a stable, non-reversible storage identifier from the raw key."""
        return hashlib.sha256(key.encode()).hexdigest()[:16]

    async def _read(self) -> dict[str, dict[str, Any]]:
        if not self._path.exists():
            return {}
        try:
            return cast(
                dict[str, dict[str, Any]],
                json.loads(self._path.read_text(encoding="utf-8")),
            )
        except (json.JSONDecodeError, OSError):
            return {}

    async def _write(self, data: dict[str, dict[str, Any]]) -> None:
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(tmp, self._path)

    async def save(self, key: str, state: dict[str, Any]) -> None:
        async with self._lock:
            data = await self._read()
            data[self._key_id(key)] = state  # store under hash, not raw key
            await self._write(data)

    async def load(self, key: str) -> dict[str, Any] | None:
        async with self._lock:
            data = await self._read()
            return data.get(self._key_id(key))

    async def load_all(self) -> dict[str, dict[str, Any]]:
        async with self._lock:
            return await self._read()

    async def delete(self, key: str) -> None:
        async with self._lock:
            data = await self._read()
            data.pop(self._key_id(key), None)
            await self._write(data)

    async def close(self) -> None:
        """No-op for JSON backend."""
