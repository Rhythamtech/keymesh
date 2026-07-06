from keymesh import KeyMeshSyncHTTPClient, SqliteMemory, RedisMemory, PostgresMemory

def main():
    print("=== SQLite Memory Backend ===")
    sqlite_mem = SqliteMemory()
    print("SQLite initial stats:", sqlite_mem.fetch_db_stats())

    print("\n=== Redis Memory Backend ===")
    try:
        redis_mem = RedisMemory(url="redis://localhost:6379/0", socket_timeout=1)
        stats = redis_mem.fetch_db_stats()
       
        print("Redis connection successful!")
        print("Redis stats:", stats)
    except Exception as e:
        print(f"Skipping live Redis demo: {e} (make sure Redis is running on localhost:6379)")

    print("\n=== Postgres Memory Backend ===")
    try:
        postgres_mem = PostgresMemory(
            conninfo="postgresql://postgres:postgres@localhost:5432/keymesh",
            connect_timeout=1
        )
        stats = postgres_mem.fetch_db_stats()
        print("Postgres connection successful!")
        print("Postgres stats:", stats)
        postgres_mem.close()
    except Exception as e:
        print(f"Skipping live Postgres demo: {e} (make sure Postgres is running on localhost:5432 with db 'keymesh')")

    print("\n=== KeyMesh Sync HTTP Client ===")
    http_client = KeyMeshSyncHTTPClient(
        keys=[
            "sk-1e6fb5d5c3012d2c-qepbpw-ebb49608",
            "sk-1e6fb5d5c3012d2c-y2oi1e-a7ccf632"
        ],
        memory=sqlite_mem,
        max_retries_per_request=3,
        cooldown_seconds=60.0,
        debug_logging=True,
    )
    print("HTTP Client seeded keys successfully!")
    print("Seeded SQLite stats:", sqlite_mem.fetch_db_stats())


if __name__ == "__main__":
    main()