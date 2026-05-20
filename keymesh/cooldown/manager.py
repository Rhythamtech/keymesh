"""
Cooldown manager — tracks and enforces per-key cooldown windows.

KeyMesh never sleeps waiting for cooldowns. Instead, unavailable keys
are filtered out at acquire-time and re-admitted when time has elapsed.
"""

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from keymesh.state.key_state import KeyState


class CooldownManager:
    """
    Stateless helper for cooldown evaluation.

    All actual cooldown state lives inside KeyState.
    This class provides higher-level helpers used by the pool.
    """

    @staticmethod
    def apply(key_state: "KeyState", duration: float = 60.0) -> None:
        """
        Immediately apply a cooldown window to a key (synchronous, for internal use).

        .. deprecated::
            This method mutates ``cooldown_until`` directly without acquiring
            the key's internal ``asyncio.Lock``, making it unsafe under
            concurrency. Use ``await key_state.apply_cooldown(duration)``
            in async contexts instead.
        """
        import warnings

        warnings.warn(
            "CooldownManager.apply() is not concurrency-safe. "
            "Use `await key_state.apply_cooldown(duration)` in async code.",
            DeprecationWarning,
            stacklevel=2,
        )
        key_state.cooldown_until = time.monotonic() + duration

    @staticmethod
    def is_expired(key_state: "KeyState") -> bool:
        """Return True if cooldown has elapsed (key may be re-admitted)."""
        return time.monotonic() >= key_state.cooldown_until

    @staticmethod
    def remaining(key_state: "KeyState") -> float:
        """Seconds until cooldown expires. Returns 0 if not cooling down."""
        return max(0.0, key_state.cooldown_until - time.monotonic())
