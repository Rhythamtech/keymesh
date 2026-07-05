import asyncio
from openai import OpenAI
from src.keymesh import KeyMeshSyncHTTPClient

def main():
    http_client = KeyMeshSyncHTTPClient(
        keys=["sk-1e6fb5d5c3012d2c-qepbpw-ebb49608",
 "sk-1e6fb5d5c3012d2c-y2oi1e-a7ccf632",
 "sk-1e6fb5d5c3012d2c-uhntvr-18e9bab9",
 "sk-1e6fb5d5c3012d2c-seghps-258482ed"],
        max_retries_per_request=3,
        cooldown_seconds=60.0,
        debug_logging=True,
    )

    client = OpenAI(
        base_url="http://localhost:20128/v1",
        api_key="placeholder",
        http_client=http_client,
        max_retries=0,  # let KeyMesh own retries
    )

    
    for i in range(30):
        response = client.chat.completions.create(
            model="oc/north-mini-code-free",
            messages=[{"role": "user", "content": "Hello KeyMesh!"+str(i)}],
        )
        print(response.choices[0].message.content)

if __name__ == "__main__":
    main()