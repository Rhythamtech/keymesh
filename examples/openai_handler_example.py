"""
KeyMesh Demonstration — Using OpenAIHandler and AsyncOpenAIHandler to
transparently multiplex API keys using the OpenAI SDK client.
"""

import os
import asyncio
from dotenv import load_dotenv
from openai import OpenAI, AsyncOpenAI
from keymesh import OpenAIHandler, AsyncOpenAIHandler, SchedulerStrategy

# Load environment variables
load_dotenv()
API_KEYS = os.getenv("OPENAI_API_KEYS", "sk-key-1,sk-key-2,sk-key-3").split(",")
BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
MODEL_NAME = os.getenv("OPENAI_MODEL_NAME", "gpt-4o")


def run_sync_demo() -> None:
    print("── Sync Handler Demo ──")
    # 1. Initialize the OpenAIHandler which acts as an httpx.Client
    handler = OpenAIHandler(
        keys=API_KEYS,
        strategy=SchedulerStrategy.ROUND_ROBIN,
    )

    # 2. Pass the handler as http_client directly to OpenAI SDK
    client = OpenAI(
        api_key="dummy",  # Replaced dynamically by transport
        base_url=BASE_URL,
        http_client=handler,
    )

    try:
        # 3. Call the SDK normally
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[{"role": "user", "content": "Say 'Multiplexed Sync' in 3 words."}],
        )
        print(f"Success: {response.choices[0].message.content}")
    except Exception as e:
        print(f"Failed: {e}")
    finally:
        # 4. View statistics and close handler
        print("Pool Status:")
        print(handler.pool.status())
        handler.close()


async def run_async_demo() -> None:
    print("\n── Async Handler Demo ──")
    # 1. Initialize the AsyncOpenAIHandler which acts as an httpx.AsyncClient
    handler = AsyncOpenAIHandler(
        keys=API_KEYS,
        strategy=SchedulerStrategy.LEAST_BUSY,
    )

    # 2. Pass the handler as http_client directly to AsyncOpenAI SDK
    client = AsyncOpenAI(
        api_key="dummy",  # Replaced dynamically by transport
        base_url=BASE_URL,
        http_client=handler,
    )

    try:
        # 3. Call the SDK normally
        response = await client.chat.completions.create(
            model=MODEL_NAME,
            messages=[{"role": "user", "content": "Say 'Multiplexed Async' in 3 words."}],
        )
        print(f"Success: {response.choices[0].message.content}")
    except Exception as e:
        print(f"Failed: {e}")
    finally:
        # 4. View statistics and close handler
        print("Pool Status:")
        print(handler.pool.status())
        await handler.aclose()


if __name__ == "__main__":
    run_sync_demo()
    asyncio.run(run_async_demo())
