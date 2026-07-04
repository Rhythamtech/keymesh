import hashlib
from typing import Final

API_HASH_LEN: Final[int] = 16

def hash_api_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:API_HASH_LEN]