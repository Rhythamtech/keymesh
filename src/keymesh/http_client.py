
import httpx
from typing import Any

from .masking import hash_api_key
from .memory import KeyMeshMemory
from .service import KeyMeshService
from .logging import KeyMeshLogger


class KeyMeshSyncHTTPClient(httpx.Client):
    """
    An httpx.Client subclass that transparently rotates API keys across a
    pool, tracks per-key RPM windows, applies cooldowns on 429 responses,
    and retries automatically — without the caller needing to know.

    Drop-in replacement for httpx.Client, compatible with the OpenAI SDK::

        client = OpenAI(
            api_key="placeholder",
            http_client=KeyMeshSyncHTTPClient(
                keys=["sk-...", "sk-..."],
            ),
            max_retries=0,
        )
    """

    def __init__(
        self,
        keys: list[str],
        db_path: str = "keymesh.db",
        max_retries_per_request: int = 3,
        cooldown_seconds: float = 60.0,
        window_seconds: int = 60,
        default_rpm: int = 60,
        timeout: float | None = None,
        debug_logging: bool = False,
        **kwargs: Any,
    ):
        super().__init__(timeout=timeout, **kwargs)

        self.max_retries_per_request = max_retries_per_request
        self.cooldown_seconds = cooldown_seconds
        self._logger = KeyMeshLogger(enabled=debug_logging)

        # Initialise database and seed every key from the pool.
        self._memory = KeyMeshMemory(db_path=db_path)
        for api_key in keys:
            api_hash = hash_api_key(api_key)
            self._memory._upsert_key_config(
                api_hash=api_hash,
                api_key=api_key,
                rpm=default_rpm,
            )

        self._service = KeyMeshService(
            memory=self._memory,
            window_seconds=window_seconds,
        )

    def send(
        self,
        request: httpx.Request,
        *,
        stream: bool = False,
        auth: httpx.Auth | None = None,
        follow_redirects: bool | None = None,
    ) -> httpx.Response:
        last_exc: Exception | None = None

        for attempt in range(self.max_retries_per_request):
            lease = self._service.acquire()

            request.headers["Authorization"] = f"Bearer {lease.api_key}"

            try:
                response = super().send(
                    request,
                    stream=stream,
                    auth=auth,
                    follow_redirects=follow_redirects,
                )
            except Exception as exc:
                self._service.release(lease.api_hash)
                self._logger.log("request_error", {
                    "api_hash": lease.api_hash,
                    "attempt": attempt + 1,
                    "error": str(exc),
                })
                last_exc = exc
                continue

            self._service.release(lease.api_hash)

            self._logger.log("request_complete", {
                "api_hash": lease.api_hash,
                "status_code": response.status_code,
                "attempt": attempt + 1,
            })

            if response.status_code == 429:
                # Key is rate-limited; put it in cooldown and try again with
                # the next best key.
                self._service.set_cooldown(lease.api_hash)
                self._logger.log("key_cooldown", {
                    "api_hash": lease.api_hash,
                    "cooldown_seconds": self.cooldown_seconds,
                })
                continue

            # For all other status codes (2xx, 4xx, 5xx) return the response
            # as-is so the caller's error-handling (e.g. OpenAI SDK) runs.
            return response

        if last_exc is not None:
            raise last_exc
        raise RuntimeError(
            f"KeyMesh: all {self.max_retries_per_request} retries exhausted "
            "(all keys may be rate-limited)."
        )