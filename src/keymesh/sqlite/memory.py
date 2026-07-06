import sqlite3
from datetime import datetime, timedelta, UTC
from typing import Final

MAX_KEY_LEASES: Final[int] = 10000

def _to_db(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.isoformat()

def _from_db(val: str | None) -> datetime | None:
    if val is None or val == "":
        return None
    val = val.replace(" ", "T")
    try:
        return datetime.fromisoformat(val)
    except ValueError:
        return datetime.strptime(val.split(".")[0], "%Y-%m-%dT%H:%M:%S")

class SqliteMemory:
    def __init__(self, db_path=":memory:", **kwargs):
        self.con = sqlite3.connect(db_path, isolation_level=None, uri=True, **kwargs)
        self._init_schema()

    def _init_schema(self):
        self.con.execute("""
            CREATE TABLE IF NOT EXISTS key_config (
                api_hash TEXT PRIMARY KEY,
                api_key TEXT NOT NULL,
                request_per_minute INTEGER NOT NULL,
                is_disable INTEGER NOT NULL DEFAULT 0,
                created_at TEXT,
                updated_at TEXT
            )
        """)
        self.con.execute("""
            CREATE TABLE IF NOT EXISTS key_state (
                api_hash TEXT PRIMARY KEY,
                window_start_at TEXT NOT NULL,
                last_used_at TEXT,
                request_count INTEGER NOT NULL,
                cooldown_until TEXT,
                last_429_at TEXT
            )
        """)
        self.con.execute("""
            CREATE TABLE IF NOT EXISTS key_lease (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                api_hash TEXT NOT NULL,
                api_key TEXT NOT NULL,
                attempt INTEGER NOT NULL,
                acquire_at TEXT NOT NULL,
                release_at TEXT
            )
        """)

    def _upsert_key_config(self, api_hash: str, api_key: str, rpm: int) -> None:
        now = datetime.now(UTC).replace(tzinfo=None)
        existing = self.con.execute(
            "SELECT api_hash FROM key_config WHERE api_hash = ?", [api_hash]
        ).fetchone()
        if existing:
            self.con.execute("""
                UPDATE key_config
                SET api_key = ?, request_per_minute = ?, updated_at = ?
                WHERE api_hash = ?
            """, [api_key, rpm, _to_db(now), api_hash])
        else:
            self.con.execute("""
                INSERT INTO key_config (api_hash, api_key, request_per_minute, is_disable, created_at, updated_at)
                VALUES (?, ?, ?, 0, ?, ?)
            """, [api_hash, api_key, rpm, _to_db(now), _to_db(now)])

    def _get_all_available_keys(self) -> list[tuple]:
        rows = self.con.execute("""
            SELECT
                c.api_hash, c.api_key, c.request_per_minute, c.is_disable,
                s.window_start_at, s.last_used_at, s.request_count, s.cooldown_until, s.last_429_at
            FROM key_config c
            LEFT JOIN key_state s ON c.api_hash = s.api_hash
            WHERE c.is_disable = 0
        """).fetchall()
        
        converted_rows = []
        for r in rows:
            api_hash, api_key, rpm, is_disable, window_start_at, last_used_at, request_count, cooldown_until, last_429_at = r
            converted_rows.append((
                api_hash,
                api_key,
                rpm,
                bool(is_disable),
                _from_db(window_start_at),
                _from_db(last_used_at),
                request_count,
                _from_db(cooldown_until),
                _from_db(last_429_at)
            ))
        return converted_rows

    def _get_choosen_key_state(self, keyhash :str ):
        state = self.con.execute(
            "SELECT api_hash, window_start_at, last_used_at, request_count, cooldown_until, last_429_at FROM key_state WHERE api_hash = ?",
            [keyhash],
        ).fetchone()
        if state is None:
            return None
        api_hash, window_start_at, last_used_at, request_count, cooldown_until, last_429_at = state
        return (
            api_hash,
            _from_db(window_start_at),
            _from_db(last_used_at),
            request_count,
            _from_db(cooldown_until),
            _from_db(last_429_at)
        )

    def _add_new_key_state(self, api_hash: str, now: datetime):
        self.con.execute("""
            INSERT INTO key_state
            (api_hash, window_start_at, last_used_at, request_count, cooldown_until, last_429_at)
            VALUES (?, ?, ?, ?, NULL, NULL)
        """, [api_hash, _to_db(now), _to_db(now), 1])

    def _increment_request_count(self, api_hash: str, now: datetime):
        self.con.execute("""
            UPDATE key_state
            SET last_used_at = ?, request_count = request_count + 1
            WHERE api_hash = ?
        """, [_to_db(now), api_hash])

    def _add_lease(self, api_hash: str, api_key: str, attempt: int, now: datetime):
        self.con.execute("""
            INSERT INTO key_lease (api_hash, api_key, attempt, acquire_at)
            VALUES (?, ?, ?, ?)
        """, [api_hash, api_key, attempt, _to_db(now)])

    def _reset_window_if_needed(self, api_hash: str, now: datetime, window_seconds: int):
        row = self.con.execute("""
            SELECT window_start_at, request_count
            FROM key_state
            WHERE api_hash = ?
        """, [api_hash]).fetchone()

        if not row:
            return

        window_start_at_str, request_count = row
        window_start_at = _from_db(window_start_at_str)
        if window_start_at is None:
            return

        if now >= window_start_at + timedelta(seconds=window_seconds):
            self.con.execute("""
                UPDATE key_state
                SET window_start_at = ?, request_count = 0
                WHERE api_hash = ?
            """, [_to_db(now), api_hash])

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
                """, [_to_db(now), api_hash])

        self.con.execute("""
            UPDATE key_state
            SET last_used_at = ?
            WHERE api_hash = ?
        """, [_to_db(now), api_hash])

    def _set_cooldown(self, api_hash: str, now: datetime):
        self.con.execute("""
            UPDATE key_state
            SET cooldown_until = ?
            WHERE api_hash = ?
        """, [_to_db(now + timedelta(minutes=1)), api_hash])

    def _begin_transaction(self):
        try:
            self.con.execute("BEGIN IMMEDIATE")
        except Exception:
            pass

    def _commit_transaction(self):
        try:
            self.con.execute("COMMIT")
        except Exception:
            pass

    def _rollback_transaction(self):
        try:
            self.con.execute("ROLLBACK")
        except Exception:
            pass

    def fetch_db_stats(self):
        """Fetch database stats for debugging/monitoring."""
        stats = {}
        try:
            # Get number of keys
            keys_count = self.con.execute("SELECT COUNT(*) FROM key_config").fetchone()[0]
            stats['total_keys'] = keys_count

            # Get number of active leases (where release_at is NULL)
            active_leases = self.con.execute("SELECT COUNT(*) FROM key_lease WHERE release_at IS NULL").fetchone()[0]
            stats['active_leases'] = active_leases

            # Get number of keys in cooldown
            cooldown_keys = self.con.execute("SELECT COUNT(*) FROM key_state WHERE cooldown_until IS NOT NULL").fetchone()[0]
            stats['keys_in_cooldown'] = cooldown_keys

            # Get total leases ever
            total_leases = self.con.execute("SELECT COUNT(*) FROM key_lease").fetchone()[0]
            stats['total_leases'] = total_leases

            # Get last lease time
            last_lease = self.con.execute("SELECT MAX(acquire_at) FROM key_lease").fetchone()[0]
            stats['last_lease_time'] = _from_db(last_lease)
        except Exception as e:
            stats['error'] = str(e)

        return stats

