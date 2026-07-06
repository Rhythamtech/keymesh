import redis
import time
from datetime import datetime, timedelta, UTC

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

class RedisMemory:
    def __init__(self, host: str = "localhost", port: int = 6379, db: int = 0, password: str | None = None, url: str | None = None, **kwargs):
        if url:
            self.redis = redis.from_url(url, decode_responses=True, **kwargs)
        else:
            self.redis = redis.Redis(host=host, port=port, db=db, password=password, decode_responses=True, **kwargs)
        self.has_lock = False

    def _upsert_key_config(self, api_hash: str, api_key: str, rpm: int) -> None:
        now = datetime.now(UTC).replace(tzinfo=None)
        cfg_key = f"keymesh:config:{api_hash}"
        created_at = self.redis.hget(cfg_key, "created_at")
        if not created_at:
            created_at = _to_db(now)
        
        self.redis.hset(cfg_key, mapping={
            "api_hash": api_hash,
            "api_key": api_key,
            "request_per_minute": str(rpm),
            "is_disable": "0",
            "created_at": created_at,
            "updated_at": _to_db(now)
        })
        self.redis.sadd("keymesh:configs", api_hash)

    def _get_all_available_keys(self) -> list[tuple]:
        api_hashes = self.redis.smembers("keymesh:configs")
        rows = []
        for api_hash in api_hashes:
            config = self.redis.hgetall(f"keymesh:config:{api_hash}")
            if not config:
                continue
            
            is_disable = int(config.get("is_disable", 0))
            if is_disable != 0:
                continue
                
            state_key = f"keymesh:state:{api_hash}"
            if not self.redis.exists(state_key):
                window_start_at = None
                last_used_at = None
                request_count = None
                cooldown_until = None
                last_429_at = None
            else:
                state = self.redis.hgetall(state_key)
                window_start_at = state.get("window_start_at")
                last_used_at = state.get("last_used_at")
                request_count_val = state.get("request_count")
                request_count = int(request_count_val) if request_count_val is not None and request_count_val != "" else 0
                cooldown_until = state.get("cooldown_until")
                last_429_at = state.get("last_429_at")

            api_key = config.get("api_key", "")
            rpm = int(config.get("request_per_minute", 60))

            rows.append((
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
        return rows

    def _get_choosen_key_state(self, keyhash: str):
        state_key = f"keymesh:state:{keyhash}"
        if not self.redis.exists(state_key):
            return None
        state = self.redis.hgetall(state_key)
        
        window_start_at = state.get("window_start_at")
        last_used_at = state.get("last_used_at")
        request_count_val = state.get("request_count")
        request_count = int(request_count_val) if request_count_val is not None and request_count_val != "" else 0
        cooldown_until = state.get("cooldown_until")
        last_429_at = state.get("last_429_at")
        
        return (
            keyhash,
            _from_db(window_start_at),
            _from_db(last_used_at),
            request_count,
            _from_db(cooldown_until),
            _from_db(last_429_at)
        )

    def _add_new_key_state(self, api_hash: str, now: datetime):
        self.redis.hset(f"keymesh:state:{api_hash}", mapping={
            "window_start_at": _to_db(now),
            "last_used_at": _to_db(now),
            "request_count": "1",
            "cooldown_until": "",
            "last_429_at": ""
        })

    def _increment_request_count(self, api_hash: str, now: datetime):
        state_key = f"keymesh:state:{api_hash}"
        self.redis.hset(state_key, "last_used_at", _to_db(now))
        self.redis.hincrby(state_key, "request_count", 1)

    def _add_lease(self, api_hash: str, api_key: str, attempt: int, now: datetime):
        lease_id = self.redis.incr("keymesh:lease:next_id")
        self.redis.hset(f"keymesh:lease:{lease_id}", mapping={
            "id": str(lease_id),
            "api_hash": api_hash,
            "api_key": api_key,
            "attempt": str(attempt),
            "acquire_at": _to_db(now),
            "release_at": ""
        })
        self.redis.set(f"keymesh:lease:latest:{api_hash}", str(lease_id))
        self.redis.sadd("keymesh:active_leases", str(lease_id))

    def _reset_window_if_needed(self, api_hash: str, now: datetime, window_seconds: int):
        state_key = f"keymesh:state:{api_hash}"
        state = self.redis.hgetall(state_key)
        if not state:
            return

        window_start_at_str = state.get("window_start_at")
        window_start_at = _from_db(window_start_at_str)
        if window_start_at is None:
            return

        if now >= window_start_at + timedelta(seconds=window_seconds):
            self.redis.hset(state_key, mapping={
                "window_start_at": _to_db(now),
                "request_count": "0"
            })

    def _release_key(self, api_hash: str, now: datetime):
        lease_id = self.redis.get(f"keymesh:lease:latest:{api_hash}")
        if lease_id:
            self.redis.hset(f"keymesh:lease:{lease_id}", "release_at", _to_db(now))
            self.redis.srem("keymesh:active_leases", lease_id)

        self.redis.hset(f"keymesh:state:{api_hash}", "last_used_at", _to_db(now))

    def _set_cooldown(self, api_hash: str, now: datetime):
        self.redis.hset(f"keymesh:state:{api_hash}", "cooldown_until", _to_db(now + timedelta(minutes=1)))

    def _begin_transaction(self):
        start_time = time.time()
        while True:
            if self.redis.set("keymesh:lock", "locked", ex=10, nx=True):
                self.has_lock = True
                break
            if time.time() - start_time > 10.0:
                raise RuntimeError("Timeout acquiring Redis lock")
            time.sleep(0.01)

    def _commit_transaction(self):
        if self.has_lock:
            self.redis.delete("keymesh:lock")
            self.has_lock = False

    def _rollback_transaction(self):
        if self.has_lock:
            self.redis.delete("keymesh:lock")
            self.has_lock = False

    def fetch_db_stats(self):
        stats = {}
        try:
            total_keys = self.redis.scard("keymesh:configs")
            stats['total_keys'] = total_keys

            active_leases = self.redis.scard("keymesh:active_leases")
            stats['active_leases'] = active_leases

            cooldown_count = 0
            api_hashes = self.redis.smembers("keymesh:configs")
            for api_hash in api_hashes:
                cooldown_until_str = self.redis.hget(f"keymesh:state:{api_hash}", "cooldown_until")
                if cooldown_until_str and cooldown_until_str != "":
                    cooldown_count += 1
            stats['keys_in_cooldown'] = cooldown_count

            next_id = self.redis.get("keymesh:lease:next_id")
            stats['total_leases'] = int(next_id) if next_id else 0

            last_lease_time = None
            if stats['total_leases'] > 0:
                acquire_at = self.redis.hget(f"keymesh:lease:{stats['total_leases']}", "acquire_at")
                last_lease_time = _from_db(acquire_at)
            stats['last_lease_time'] = last_lease_time
        except Exception as e:
            stats['error'] = str(e)

        return stats

    def flush_all(self):
        keys = self.redis.keys("keymesh:*")
        if keys:
            self.redis.delete(*keys)

