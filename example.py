"""
KeyMesh Demonstration — Basic implementation showcasing both Sync and Async KeyPools.
"""

import os
import asyncio
import time
from dotenv import load_dotenv
from openai import OpenAI, AsyncOpenAI
from keymesh import KeyPool, SyncKeyPool

# Demonstration credentials

load_dotenv()
API_KEYS = os.getenv("OPENAI_API_KEYS","").split(",")
BASE_URL = os.getenv("OPENAI_BASE_URL","")
MODEL_NAME = os.getenv("OPENAI_MODEL_NAME","")

# ── 1. Synchronous Example (Thread-safe, Blocking) ──────────────────────────
def run_sync_example() -> None:
    print("── Running Synchronous Demo ──")
    pool = SyncKeyPool(keys=API_KEYS)
    
    # Acquire key synchronously
    key = pool.acquire()
    client = OpenAI(base_url=BASE_URL, api_key=key)
    
    start = time.monotonic()
    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[{"role": "user", "content": "Tell me a 1-sentence joke."}],
        )
        # Release key and track latency
        pool.release(key, latency=time.monotonic() - start)
        print(f"Sync Success: {response.choices[0].message.content}")
    except Exception as e:
        print(f"Sync Failed: {e}")
        pool.mark_failed(key)
    finally:
        pool.close()


# ── 2. Asynchronous Example (Asyncio-safe) ──────────────────────────────────
async def run_async_example() -> None:
    print("\n── Running Asynchronous Demo ──")
    pool = KeyPool(keys=API_KEYS)
    
    # Acquire key asynchronously
    key = await pool.acquire()
    client = AsyncOpenAI(base_url=BASE_URL, api_key=key)
    
    start = time.monotonic()
    try:
        response = await client.chat.completions.create(
            model=MODEL_NAME,
            messages=[{"role": "user", "content": "Tell me a 1-sentence joke."}],
        )
        # Release key and track latency
        await pool.release(key, latency=time.monotonic() - start)
        print(f"Async Success: {response.choices[0].message.content}")
    except Exception as e:
        print(f"Async Failed: {e}")
        await pool.mark_failed(key)
    finally:
        await pool.close()


if __name__ == "__main__":
    run_sync_example()
    asyncio.run(run_async_example())
