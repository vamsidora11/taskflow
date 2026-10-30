class HealthService:
    """Dependency probes for the readiness endpoint.

    Phase 1 replaces the placeholders with real Postgres and Redis checks.
    """

    async def check_database(self) -> str:
        return "not_configured"

    async def check_redis(self) -> str:
        return "not_configured"

    async def check_readiness(self) -> dict[str, str]:
        return {
            "database": await self.check_database(),
            "redis": await self.check_redis(),
        }
