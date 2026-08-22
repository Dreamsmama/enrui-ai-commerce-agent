"""Create the application PostgreSQL database and OSS prefix, then verify Redis.

Run from backend with the admin database URL and cloud credentials supplied only
through environment variables. This script never writes or prints secrets.
"""
from __future__ import annotations

import os
import re
import sys
from urllib.parse import urlsplit, urlunsplit


DATABASE_NAME = os.getenv("APP_DATABASE_NAME", "enrui_ai_commerce_agent")
OSS_PREFIX = os.getenv("ALIYUN_OSS_PREFIX", "enrui-ai-commerce-agent/").strip("/") + "/"


def create_database() -> None:
    import psycopg
    from psycopg import sql

    admin_url = os.environ["POSTGRES_ADMIN_URL"].replace("postgresql+psycopg://", "postgresql://")
    parsed = urlsplit(admin_url)
    maintenance_url = urlunsplit((parsed.scheme, parsed.netloc, "/postgres", parsed.query, parsed.fragment))
    if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", DATABASE_NAME):
        raise ValueError("APP_DATABASE_NAME 不是安全的 PostgreSQL 标识符")
    with psycopg.connect(maintenance_url, autocommit=True) as connection:
        exists = connection.execute("SELECT 1 FROM pg_database WHERE datname = %s", (DATABASE_NAME,)).fetchone()
        if not exists:
            connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(DATABASE_NAME)))
            print(f"PostgreSQL database created: {DATABASE_NAME}")
        else:
            print(f"PostgreSQL database already exists: {DATABASE_NAME}")


def create_oss_prefix() -> None:
    import oss2

    endpoint = os.environ["ALIYUN_OSS_ENDPOINT"].removeprefix("https://").removeprefix("http://")
    auth = oss2.Auth(os.environ["ALIYUN_OSS_ACCESS_KEY_ID"], os.environ["ALIYUN_OSS_ACCESS_KEY_SECRET"])
    bucket = oss2.Bucket(auth, f"https://{endpoint}", os.environ["ALIYUN_OSS_BUCKET_NAME"])
    bucket.put_object(OSS_PREFIX, b"")
    print(f"OSS prefix ready: {OSS_PREFIX}")


def verify_redis() -> None:
    import redis

    client = redis.Redis.from_url(os.environ["REDIS_URL"], socket_connect_timeout=5)
    if not client.ping():
        raise RuntimeError("Redis PING failed")
    print("Redis connection: ok")


def main() -> int:
    required = [
        "POSTGRES_ADMIN_URL", "REDIS_URL", "ALIYUN_OSS_ENDPOINT",
        "ALIYUN_OSS_ACCESS_KEY_ID", "ALIYUN_OSS_ACCESS_KEY_SECRET", "ALIYUN_OSS_BUCKET_NAME",
    ]
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        print("Missing environment variables: " + ", ".join(missing), file=sys.stderr)
        return 2
    failures = []
    for name, operation in (
        ("PostgreSQL", create_database),
        ("OSS", create_oss_prefix),
        ("Redis", verify_redis),
    ):
        try:
            operation()
        except Exception as exc:
            failures.append(name)
            print(f"{name} failed: {type(exc).__name__}: {exc}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
