from .http_client import KeyMeshSyncHTTPClient
from .sqlite.memory import SqliteMemory

def __getattr__(name: str):
    if name == "RedisMemory":
        try:
            from .redis.memory import RedisMemory
        except ImportError:
            raise ImportError(
                "'RedisMemory' requires the 'redis' package. "
                "Install it with: uv add redis  or  pip install redis"
            )
        return RedisMemory

    if name == "PostgresMemory":
        try:
            from .postgres.memory import PostgresMemory
        except ImportError:
            raise ImportError(
                "'PostgresMemory' requires the 'psycopg' package. "
                "Install it with: uv add 'psycopg[binary]'  or  pip install 'psycopg[binary]'"
            )
        return PostgresMemory

    raise AttributeError(f"module 'keymesh' has no attribute {name!r}")

__all__ = [
    "KeyMeshSyncHTTPClient",
    "SqliteMemory",
    "RedisMemory",
    "PostgresMemory",
]
