import os

import pytest
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.services.health import HealthService

UNREACHABLE_REDIS = "redis://127.0.0.1:1/0"
UNREACHABLE_DB = "postgresql+asyncpg://nobody:nopass@127.0.0.1:1/none"


async def test_database_probe_ok(app_engine: AsyncEngine) -> None:
    redis = Redis.from_url(UNREACHABLE_REDIS)
    try:
        assert await HealthService(app_engine, redis).check_database() == "ok"
    finally:
        await redis.aclose()


async def test_database_probe_error_when_unreachable() -> None:
    engine = create_async_engine(UNREACHABLE_DB)
    redis = Redis.from_url(UNREACHABLE_REDIS)
    try:
        assert await HealthService(engine, redis).check_database() == "error"
    finally:
        await redis.aclose()
        await engine.dispose()


async def test_readiness_reports_both_dependencies_down() -> None:
    engine = create_async_engine(UNREACHABLE_DB)
    redis = Redis.from_url(UNREACHABLE_REDIS)
    try:
        service = HealthService(engine, redis)
        assert await service.check_redis() == "error"
        assert await service.check_readiness() == {"database": "error", "redis": "error"}
    finally:
        await redis.aclose()
        await engine.dispose()


async def test_redis_probe_ok() -> None:
    redis = Redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
    engine = create_async_engine(UNREACHABLE_DB)
    try:
        try:
            await redis.ping()
        except Exception:
            if os.environ.get("CI"):
                raise
            pytest.skip("Redis not reachable; set REDIS_URL")
        assert await HealthService(engine, redis).check_redis() == "ok"
    finally:
        await redis.aclose()
        await engine.dispose()
