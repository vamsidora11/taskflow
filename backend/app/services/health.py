import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Literal

from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

PROBE_TIMEOUT_SECONDS = 2.0

ProbeState = Literal["ok", "error"]

logger = logging.getLogger(__name__)


class HealthService:
    """Dependency probes for the readiness endpoint. Each probe returns `ok` or `error`."""

    def __init__(self, engine: AsyncEngine, redis: Redis) -> None:
        self._engine = engine
        self._redis = redis

    async def check_database(self) -> ProbeState:
        async def probe() -> None:
            async with self._engine.connect() as conn:
                await conn.execute(text("SELECT 1"))

        return await self._run("database", probe)

    async def check_redis(self) -> ProbeState:
        async def probe() -> None:
            await self._redis.ping()

        return await self._run("redis", probe)

    async def check_readiness(self) -> dict[str, ProbeState]:
        database, redis = await asyncio.gather(self.check_database(), self.check_redis())
        return {"database": database, "redis": redis}

    @staticmethod
    async def _run(name: str, probe: Callable[[], Awaitable[None]]) -> ProbeState:
        try:
            await asyncio.wait_for(probe(), timeout=PROBE_TIMEOUT_SECONDS)
        except Exception:
            logger.warning("readiness probe failed: %s", name, exc_info=True)
            return "error"
        return "ok"
