import hashlib


API_HASH_LEN = 16

def hash_api_key(api_key: str) -> str:
    """Return the first 16 chars of the SHA256 hash of the API key."""
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:API_HASH_LEN]