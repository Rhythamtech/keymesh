"""
Utility helpers for KeyMesh.
"""

import logging
import time
from functools import wraps
from typing import Any, Callable


def setup_logging(level: str = "INFO") -> None:
    """Configure basic logging for KeyMesh. Call once at application startup."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )


def now() -> float:
    """Return current monotonic clock value."""
    return time.monotonic()


def mask_key(key: str, visible_chars: int = 6) -> str:
    """Return a masked version of a key for safe logging."""
    if len(key) <= visible_chars:
        return "***"
    return f"...{key[-visible_chars:]}"


def retry_on(
    *exceptions: type[Exception],
    max_retries: int = 3,
    delay: float = 0.5,
) -> Callable:
    """
    Simple synchronous retry decorator for non-async functions.

    For async retry logic, the KeyPool handles it natively.
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exc: Exception | None = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:
                    last_exc = exc
                    if attempt < max_retries - 1:
                        time.sleep(delay)
            raise last_exc  # type: ignore[misc]

        return wrapper

    return decorator
