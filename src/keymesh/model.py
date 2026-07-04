from dataclasses import dataclass
from datetime import datetime

@dataclass
class KeyConfig:
    api_hash : str
    api_key : str
    request_per_minute : int
    is_disable : bool = False
    # created_at : datetime
    # updated_at : datetime

@dataclass
class KeyState:
    api_hash : str
    window_start_at : datetime
    last_used_at : datetime | None
    request_count : int
    cooldown_until : datetime | None
    last_429_at : datetime | None

@dataclass
class KeyLease:
    api_hash : str
    api_key : str
    attempt : int
    acquire_at : datetime
    release_at : datetime
    