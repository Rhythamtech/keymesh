"""
KeyMesh Demonstration — Basic implementation showcasing three concurrency-safe approaches
for managing API keys in both Sync and Async KeyPools.
"""

import os
import asyncio
import time
import contextlib
from typing import Generator, AsyncGenerator
from dotenv import load_dotenv
from openai import OpenAI, AsyncOpenAI, OpenAIError, RateLimitError
from keymesh import KeyPool, SyncKeyPool

# Load environment variables
load_dotenv()
API_KEYS = os.getenv("OPENAI_API_KEYS", "").split(",")
BASE_URL = os.getenv("OPENAI_BASE_URL", "")
MODEL_NAME = os.getenv("OPENAI_MODEL_NAME", "")

# Initialize client instances once (reusing connection pools)
sync_client = OpenAI(base_url=BASE_URL)
async_client = AsyncOpenAI(base_url=BASE_URL)


# ── APPROACH 1: Request-Scoped Client Overrides (with_options) ──────────────

def run_sync_with_options(pool: SyncKeyPool) -> None:
    print("── Sync Approach 1: with_options ──")
    try:
        key = pool.acquire()
        start = time.monotonic()
        try:
            # with_options returns a copy sharing the connection pool
            scoped_client = sync_client.with_options(api_key=key)
            response = scoped_client.chat.completions.create(
                model=MODEL_NAME,
                messages=[{"role": "user", "content": "Say 'Options Sync' in 3 words."}],
            )
            pool.release(key, latency=time.monotonic() - start)
            print(f"Success: {response.choices[0].message.content}")
        except BaseException:
            pool.mark_failed(key)
            raise
    except Exception as e:
        print(f"Failed: {e}")


async def run_async_with_options(pool: KeyPool) -> None:
    print("\n── Async Approach 1: with_options ──")
    try:
        key = await pool.acquire()
        start = time.monotonic()
        try:
            scoped_client = async_client.with_options(api_key=key)
            response = await scoped_client.chat.completions.create(
                model=MODEL_NAME,
                messages=[{"role": "user", "content": "Say 'Options Async' in 3 words."}],
            )
            await pool.release(key, latency=time.monotonic() - start)
            print(f"Success: {response.choices[0].message.content}")
        except BaseException:
            await pool.mark_failed(key)
            raise
    except Exception as e:
        print(f"Failed: {e}")


# ── APPROACH 2: Per-Request Custom Headers (extra_headers) ──────────────────

def run_sync_headers(pool: SyncKeyPool) -> None:
    print("\n── Sync Approach 2: extra_headers ──")
    try:
        key = pool.acquire()
        start = time.monotonic()
        try:
            # Pass the Authorization header dynamically per-request
            response = sync_client.chat.completions.create(
                model=MODEL_NAME,
                messages=[{"role": "user", "content": "Say 'Headers Sync' in 3 words."}],
                extra_headers={"Authorization": f"Bearer {key}"}
            )
            pool.release(key, latency=time.monotonic() - start)
            print(f"Success: {response.choices[0].message.content}")
        except BaseException:
            pool.mark_failed(key)
            raise
    except Exception as e:
        print(f"Failed: {e}")


async def run_async_headers(pool: KeyPool) -> None:
    print("\n── Async Approach 2: extra_headers ──")
    try:
        key = await pool.acquire()
        start = time.monotonic()
        try:
            response = await async_client.chat.completions.create(
                model=MODEL_NAME,
                messages=[{"role": "user", "content": "Say 'Headers Async' in 3 words."}],
                extra_headers={"Authorization": f"Bearer {key}"}
            )
            await pool.release(key, latency=time.monotonic() - start)
            print(f"Success: {response.choices[0].message.content}")
        except BaseException:
            await pool.mark_failed(key)
            raise
    except Exception as e:
        print(f"Failed: {e}")


# ── APPROACH 3: Lifecycle Hooks (Context Managers) ──────────────────────────

@contextlib.contextmanager
def sync_key_lifecycle(pool: SyncKeyPool) -> Generator[str, None, None]:
    key = pool.acquire()
    start = time.monotonic()
    try:
        yield key
        pool.release(key, latency=time.monotonic() - start)
    except RateLimitError:
        pool.mark_rate_limited(key, cooldown=60.0)
        raise
    except BaseException:
        pool.mark_failed(key)
        raise


@contextlib.asynccontextmanager
async def async_key_lifecycle(pool: KeyPool) -> AsyncGenerator[str, None]:
    key = await pool.acquire()
    start = time.monotonic()
    try:
        yield key
        await pool.release(key, latency=time.monotonic() - start)
    except RateLimitError:
        await pool.mark_rate_limited(key, cooldown=60.0)
        raise
    except BaseException:
        await pool.mark_failed(key)
        raise


def run_sync_lifecycle(pool: SyncKeyPool) -> None:
    print("\n── Sync Approach 3: Lifecycle Hook ──")
    try:
        with sync_key_lifecycle(pool) as key:
            scoped_client = sync_client.with_options(api_key=key)
            response = scoped_client.chat.completions.create(
                model=MODEL_NAME,
                messages=[{"role": "user", "content": "Say 'Lifecycle Sync' in 3 words."}],
            )
            print(f"Success: {response.choices[0].message.content}")
    except Exception as e:
        print(f"Failed: {e}")


async def run_async_lifecycle(pool: KeyPool) -> None:
    print("\n── Async Approach 3: Lifecycle Hook ──")
    try:
        async with async_key_lifecycle(pool) as key:
            scoped_client = async_client.with_options(api_key=key)
            response = await scoped_client.chat.completions.create(
                model=MODEL_NAME,
                messages=[{"role": "user", "content": "Say 'Lifecycle Async' in 3 words."}],
            )
            print(f"Success: {response.choices[0].message.content}")
    except Exception as e:
        print(f"Failed: {e}")


# ── MAIN EXECUTION ──────────────────────────────────────────────────────────

async def run_all_async(async_pool: KeyPool) -> None:
    await run_async_with_options(async_pool)
    await run_async_headers(async_pool)
    await run_async_lifecycle(async_pool)


if __name__ == "__main__":
    # Create the pools
    sync_pool = SyncKeyPool(keys=API_KEYS)
    async_pool = KeyPool(keys=API_KEYS)

    try:
        # Run Synchronous Demos
        run_sync_with_options(sync_pool)
        run_sync_headers(sync_pool)
        run_sync_lifecycle(sync_pool)

        # Run Asynchronous Demos
        asyncio.run(run_all_async(async_pool))
    finally:
        # Safely close pools to release storage backends
        sync_pool.close()
        asyncio.run(async_pool.close())
