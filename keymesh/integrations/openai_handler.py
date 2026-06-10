"""
OpenAI Integration Handlers.

Provides OpenAIHandler and AsyncOpenAIHandler which subclass httpx.Client and
httpx.AsyncClient respectively. They intercept requests, inject API keys from
a scheduler pool, and update cooldown/failure states automatically based on responses.
"""

import time
import logging
from typing import Any, Sequence

import httpx
from keymesh.pool.pool import KeyPool
from keymesh.pool.sync_pool import SyncKeyPool
from keymesh.scheduler.base import SchedulerStrategy

logger = logging.getLogger(__name__)


def _parse_retry_after(response: httpx.Response) -> float | None:
    """
    Parse Retry-After header if present.

    Returns float seconds, or None if not present or invalid.
    """
    retry_after = response.headers.get("Retry-After")
    if not retry_after:
        return None
    try:
        return float(retry_after)
    except ValueError:
        # Retry-After can also be a HTTP-date, but we'll fallback to default
        # cooldown since parsing HTTP dates is complex and rare for OpenAI 429s.
        return None


class SyncKeymeshTransport(httpx.BaseTransport):
    """
    Sync Transport wrapping a base transport.
    
    Intercepts handle_request to lease a key from the SyncKeyPool, injects it
    into the Authorization header, tracks latency, and reports failure/rate limits.
    """

    def __init__(self, base_transport: httpx.BaseTransport, pool: SyncKeyPool) -> None:
        self._base_transport = base_transport
        self._pool = pool

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        key = self._pool.acquire()
        start = time.monotonic()
        # Override client-wide key dynamically per request
        request.headers["Authorization"] = f"Bearer {key}"
        try:
            response = self._base_transport.handle_request(request)
            latency = time.monotonic() - start
            if response.status_code == 429:
                cooldown_dur = _parse_retry_after(response) or self._pool._default_cooldown
                self._pool.mark_rate_limited(key, cooldown=cooldown_dur)
            else:
                self._pool.release(key, latency=latency)
            return response
        except Exception as exc:
            try:
                self._pool.mark_failed(key)
            except Exception as pool_exc:
                logger.warning("Error marking key as failed: %s", pool_exc)
            raise exc

    def close(self) -> None:
        self._base_transport.close()


class AsyncKeymeshTransport(httpx.AsyncBaseTransport):
    """
    Async Transport wrapping a base async transport.
    
    Intercepts handle_async_request to lease a key from the KeyPool, injects it
    into the Authorization header, tracks latency, and reports failure/rate limits.
    """

    def __init__(self, base_transport: httpx.AsyncBaseTransport, pool: KeyPool) -> None:
        self._base_transport = base_transport
        self._pool = pool

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        key = await self._pool.acquire()
        start = time.monotonic()
        # Override client-wide key dynamically per request
        request.headers["Authorization"] = f"Bearer {key}"
        try:
            response = await self._base_transport.handle_async_request(request)
            latency = time.monotonic() - start
            if response.status_code == 429:
                cooldown_dur = _parse_retry_after(response) or self._pool._default_cooldown
                await self._pool.mark_rate_limited(key, cooldown=cooldown_dur)
            else:
                await self._pool.release(key, latency=latency)
            return response
        except Exception as exc:
            try:
                await self._pool.mark_failed(key)
            except Exception as pool_exc:
                logger.warning("Error marking key as failed: %s", pool_exc)
            raise exc

    async def aclose(self) -> None:
        await self._base_transport.aclose()


class OpenAIHandler(httpx.Client):
    """
    A custom sync HTTP client that wraps KeyMesh SyncKeyPool scheduling.
    
    Can be passed directly as the `http_client` to the OpenAI SDK client:
    
        handler = OpenAIHandler(keys=["sk-1", "sk-2"])
        client = OpenAI(api_key="dummy", http_client=handler)
    """

    def __init__(
        self,
        keys: Sequence[str],
        *,
        strategy: SchedulerStrategy = SchedulerStrategy.LEAST_BUSY,
        default_cooldown: float = 60.0,
        max_failures: int = 10,
        acquire_timeout: float = 30.0,
        **httpx_kwargs: Any,
    ) -> None:
        self._pool = SyncKeyPool(
            keys=keys,
            strategy=strategy,
            default_cooldown=default_cooldown,
            max_failures=max_failures,
            acquire_timeout=acquire_timeout,
        )
        base_transport = httpx_kwargs.pop("transport", None) or httpx.HTTPTransport()
        transport = SyncKeymeshTransport(base_transport, self._pool)
        super().__init__(transport=transport, **httpx_kwargs)

    @property
    def pool(self) -> SyncKeyPool:
        """The underlying SyncKeyPool instance for diagnostics/management."""
        return self._pool

    def close(self) -> None:
        super().close()
        self._pool.close()


class AsyncOpenAIHandler(httpx.AsyncClient):
    """
    A custom async HTTP client that wraps KeyMesh KeyPool scheduling.
    
    Can be passed directly as the `http_client` to the AsyncOpenAI SDK client:
    
        handler = AsyncOpenAIHandler(keys=["sk-1", "sk-2"])
        client = AsyncOpenAI(api_key="dummy", http_client=handler)
    """

    def __init__(
        self,
        keys: Sequence[str],
        *,
        strategy: SchedulerStrategy = SchedulerStrategy.LEAST_BUSY,
        default_cooldown: float = 60.0,
        max_failures: int = 10,
        acquire_timeout: float = 30.0,
        **httpx_kwargs: Any,
    ) -> None:
        self._pool = KeyPool(
            keys=keys,
            strategy=strategy,
            default_cooldown=default_cooldown,
            max_failures=max_failures,
            acquire_timeout=acquire_timeout,
        )
        base_transport = httpx_kwargs.pop("transport", None) or httpx.AsyncHTTPTransport()
        transport = AsyncKeymeshTransport(base_transport, self._pool)
        super().__init__(transport=transport, **httpx_kwargs)

    @property
    def pool(self) -> KeyPool:
        """The underlying KeyPool instance for diagnostics/management."""
        return self._pool

    async def aclose(self) -> None:
        await super().aclose()
        await self._pool.close()
