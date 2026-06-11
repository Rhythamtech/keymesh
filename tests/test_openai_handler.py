"""
Unit tests for the OpenAI integration handlers.
"""

import httpx
import pytest
from keymesh import OpenAIHandler, AsyncOpenAIHandler, SchedulerStrategy
from keymesh.exceptions import NoAvailableKeyError


def test_sync_openai_handler_success() -> None:
    # Set up mock base transport returning 200 OK
    mock_transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"result": "ok"})
    )

    keys = ["keysync1", "keysync2"]
    # We pass the transport via httpx_kwargs (**httpx_kwargs)
    handler = OpenAIHandler(
        keys=keys,
        strategy=SchedulerStrategy.ROUND_ROBIN,
        transport=mock_transport,
    )

    # First request
    response1 = handler.request("POST", "https://api.openai.com/v1/chat/completions")
    assert response1.status_code == 200
    assert response1.json() == {"result": "ok"}
    # The pool statistics should show active requests and latency recorded
    status = handler.pool.status()
    # Find the state of the first key in the list (ROUND_ROBIN strategy)
    k1_state = next(k for k in status["keys"] if "sync1" in k["key_suffix"])
    assert k1_state["success_count"] == 1
    assert k1_state["latency_avg"] >= 0.0

    # Second request should rotate to the second key
    response2 = handler.request("POST", "https://api.openai.com/v1/chat/completions")
    assert response2.status_code == 200
    status = handler.pool.status()
    k2_state = next(k for k in status["keys"] if "sync2" in k["key_suffix"])
    assert k2_state["success_count"] == 1

    handler.close()


def test_sync_openai_handler_rate_limited() -> None:
    # Set up mock base transport returning 429
    mock_transport = httpx.MockTransport(
        lambda request: httpx.Response(429, headers={"Retry-After": "10"})
    )

    keys = ["sk-sync-ratelimit"]
    # Low acquire_timeout so it fails fast when key is rate limited
    handler = OpenAIHandler(
        keys=keys,
        acquire_timeout=0.1,
        transport=mock_transport,
    )

    response = handler.request("POST", "https://api.openai.com/v1/chat/completions")
    assert response.status_code == 429
    
    # Check that cooldown is applied
    assert handler.pool.available_count() == 0
    status = handler.pool.status()
    k_state = status["keys"][0]
    assert k_state["cooldown_until"] > 0.0

    # Next call should raise NoAvailableKeyError as all keys are cooling down
    with pytest.raises(NoAvailableKeyError):
        handler.request("POST", "https://api.openai.com/v1/chat/completions")

    handler.close()


def test_sync_openai_handler_failure() -> None:
    # Transport raises an error (network error scenario)
    def raise_error(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection failed")

    mock_transport = httpx.MockTransport(raise_error)

    keys = ["sk-sync-fail"]
    # Low max_failures so we exhaust it immediately
    handler = OpenAIHandler(
        keys=keys,
        max_failures=1,
        transport=mock_transport,
    )

    with pytest.raises(httpx.ConnectError):
        handler.request("POST", "https://api.openai.com/v1/chat/completions")

    # The key should be marked as failed / exhausted
    status = handler.pool.status()
    k_state = status["keys"][0]
    assert k_state["failure_count"] == 1
    assert k_state["is_available"] is False
    assert handler.pool.available_count() == 0

    handler.close()


@pytest.mark.asyncio
async def test_async_openai_handler_success() -> None:
    mock_transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"result": "async-ok"})
    )

    keys = ["keyasync1", "keyasync2"]
    handler = AsyncOpenAIHandler(
        keys=keys,
        strategy=SchedulerStrategy.ROUND_ROBIN,
        transport=mock_transport,
    )

    response1 = await handler.request("POST", "https://api.openai.com/v1/chat/completions")
    assert response1.status_code == 200
    assert response1.json() == {"result": "async-ok"}
    
    status = handler.pool.status()
    k1_state = next(k for k in status["keys"] if "async1" in k["key_suffix"])
    assert k1_state["success_count"] == 1

    await handler.aclose()
