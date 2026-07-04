from datetime import timedelta
import duckdb
from datetime import datetime
from typing import Final
from .model import KeyConfig, KeyState, KeyLease

MAX_KEY_LEASES: Final[int] = 10000

class KeyMeshMemory:
    def __init__(self, db_path=":memory:"):
        self.con = duckdb.connect(db_path)
        self._init_schema()

    def _init_schema(self):
        self.con.execute("""
            CREATE TABLE IF NOT EXISTS key_config (
                api_hash VARCHAR PRIMARY KEY,
                api_key VARCHAR NOT NULL,
                request_per_minute INTEGER NOT NULL,
                is_disable BOOLEAN NOT NULL DEFAULT FALSE,
                created_at TIMESTAMP,
                updated_at TIMESTAMP
            )
        """)
        self.con.execute("""
            CREATE TABLE IF NOT EXISTS key_state (
                api_hash VARCHAR PRIMARY KEY,
                window_start_at TIMESTAMP NOT NULL,
                last_used_at TIMESTAMP,
                request_count INTEGER NOT NULL,
                cooldown_until TIMESTAMP,
                last_429_at TIMESTAMP
            )
        """)
        self.con.execute("""
            CREATE TABLE IF NOT EXISTS key_lease (
                id BIGINT GENERATED ALWAYS AS IDENTITY,
                api_hash VARCHAR NOT NULL,
                api_key VARCHAR NOT NULL,
                attempt INTEGER NOT NULL,
                acquire_at TIMESTAMP NOT NULL,
                release_at TIMESTAMP NOT NULL
            )
        """)

    def _get_all_available_keys(self) -> list[tuple]:
        rows = self.con.execute("""
            SELECT
                c.api_hash, c.api_key, c.request_per_minute, c.is_disable,
                s.window_start_at, s.last_used_at, s.request_count, s.cooldown_until, s.last_429_at
            FROM key_config c
            LEFT JOIN key_state s ON c.api_hash = s.api_hash
            WHERE c.is_disable = FALSE
        """).fetchall()
        return rows

    def _get_choosen_key_state(self, keyhash :str ):
        state = self.con.execute(
            "SELECT api_hash, window_start_at, last_used_at, request_count, cooldown_until, last_429_at FROM key_state WHERE api_hash = ?",
            [keyhash],
        ).fetchone()
        return state

    def _add_new_key_state(self, api_hash: str, now: datetime):
        self.con.execute("""
            INSERT INTO key_state
            (api_hash, window_start_at, last_used_at, request_count, cooldown_until, last_429_at)
            VALUES (?, ?, ?, ?, NULL, NULL)
        """, [api_hash, now, now, 1])

    def _increment_request_count(self, api_hash: str, now: datetime):
        self.con.execute("""
            UPDATE key_state
            SET last_used_at = ?, request_count = request_count + 1
            WHERE api_hash = ?
        """, [now, api_hash])

    def _add_lease(self, api_hash: str, api_key: str, attempt: int, now: datetime):
        self.con.execute("""
            INSERT INTO key_lease (api_hash, api_key, attempt, acquire_at, release_at)
            VALUES (?, ?, ?, ?, ?)
        """, [api_hash, api_key, attempt, now, now])

    def _reset_window_if_needed(self, api_hash: str, now: datetime):
        row = self.con.execute("""
            SELECT window_start_at, request_count
            FROM key_state
            WHERE api_hash = ?
        """, [api_hash]).fetchone()

        if not row:
            return

        window_start_at, request_count = row
        if window_start_at is None:
            return

        if now >= window_start_at + timedelta(seconds=self.window_seconds):
            self.con.execute("""
                UPDATE key_state
                SET window_start_at = ?, request_count = 0
                WHERE api_hash = ?
            """, [now, api_hash])

    def _release_key(self, api_hash: str, now: datetime):
        self.con.execute("""
                UPDATE key_lease
                SET release_at = ?
                WHERE id = (
                        SELECT id
                        FROM key_lease
                        WHERE api_hash = ?
                        ORDER BY id DESC
                        LIMIT 1
                    )
                """, [now, api_hash])

        self.con.execute("""
            UPDATE key_state
            SET last_used_at = ?
            WHERE api_hash = ?
        """, [now, api_hash])

    def _set_cooldown(self, api_hash: str, now: datetime):
        self.con.execute("""
            UPDATE key_state
            SET cooldown_until = ?
            WHERE api_hash = ?
        """, [now + timedelta(minutes=1), api_hash])

    def _begin_transaction(self):
        try:
            self.con.execute("BEGIN TRANSACTION")
        except Exception:
            pass

    def _commit_transaction(self):
        try:
            self.con.execute("COMMIT")
        except Exception:
            pass

    def _rollback_transaction(self):
        self.con.execute("ROLLBACK")

    