from keymesh.model import KeyLease
from datetime import timedelta, datetime
from keymesh.memory import KeyMeshMemory

class KeyMeshService :
    def __init__(self, memory : KeyMeshMemory, window_seconds : int):
        self.memory = memory
        self.window_seconds = window_seconds
    
    def acquire(self) -> KeyLease:
        now = datetime.utcnow()
        self.memory._begin_transaction()
        try:
            rows = self.memory._get_all_available_keys()

            candidates = []
            for row in rows:
                api_hash, api_key, rpm, is_disable, window_start_at, last_used_at, request_count, cooldown_until, last_429_at = row
                if cooldown_until and cooldown_until > now:
                    continue

                if request_count is None:
                    request_count = 0

                if request_count is not None and request_count >= rpm:
                    continue
                
                if window_start_at and now >= window_start_at + timedelta(seconds=self.window_seconds):
                    self.memory._reset_window_if_needed(api_hash=api_hash, now = now)

                candidates.append({
                    "api_hash": api_hash,
                    "api_key": api_key,
                    "rpm": rpm,
                    "window_start_at": window_start_at,
                    "last_used_at": last_used_at,
                    "request_count": request_count or 0,
                })

            if not candidates:
                raise RuntimeError("No available key")

            candidates.sort(key=lambda x: (
                x["request_count"],
                x["last_used_at"] or datetime.min,
                x["window_start_at"] or datetime.min,
            ))
            chosen = candidates[0]

            state = self.memory._get_choosen_key_state(chosen["api_hash"])

            if state is None:
                self.memory._add_new_key_state(api_hash = chosen["api_hash"], now = now)
                attempt = 1
            else:
                self.memory._increment_request_count(api_hash=chosen["api_hash"], now=now)
                attempt = chosen["request_count"] + 1

            self.memory._add_lease(api_hash=chosen["api_hash"], api_key=chosen["api_key"], attempt=attempt, now=now)

            self.memory._commit_transaction()
            return KeyLease(api_hash=chosen["api_hash"], api_key=chosen["api_key"], attempt=attempt, acquire_at=now, release_at=now)

        except Exception:
            self.memory._rollback_transaction()
            raise

    def release(self, api_hash: str) -> None:
        now = datetime.utcnow()
        self.memory._begin_transaction()
        try:
            self.memory._release_key(api_hash = api_hash, now = now)
            self.memory._commit_transaction()
        except Exception:
            self.memory._rollback_transaction()
            raise