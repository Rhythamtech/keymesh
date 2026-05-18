"""
KeyMesh custom exceptions.
"""


class KeyMeshError(Exception):
    """Base exception for all KeyMesh errors."""


class NoAvailableKeyError(KeyMeshError):
    """Raised when no API key is currently available (all cooling down or failed)."""


class KeyCooldownError(KeyMeshError):
    """Raised when a specific key is in cooldown and cannot be used."""

    def __init__(self, key: str, cooldown_remaining: float) -> None:
        self.key = key
        self.cooldown_remaining = cooldown_remaining
        super().__init__(
            f"Key ...{key[-6:]} is in cooldown for {cooldown_remaining:.1f}s more."
        )


class KeyExhaustedError(KeyMeshError):
    """Raised when a key has exceeded its failure threshold and is removed from the pool."""

    def __init__(self, key: str) -> None:
        self.key = key
        super().__init__(f"Key ...{key[-6:]} has been exhausted and removed from pool.")
