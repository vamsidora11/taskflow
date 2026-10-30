"""Redis-backed fixed-window rate limiting (PLAN.md section 9).

Each check is one MULTI/EXEC transaction (INCR, EXPIRE NX, TTL), so concurrent requests cannot
under-count. If Redis is unreachable the limiter fails OPEN: the API stays available and the
failure is logged. The trade-off is that during a Redis outage there is no throttling, so brute
force protection is degraded until it recovers; availability was judged more important than
strictness for this service.
"""

import hashlib
import logging
import re
from dataclasses import dataclass

from redis.asyncio import Redis
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)

_UNITS = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}
_PATTERN = re.compile(r"^\s*(\d+)\s*/\s*(\d+)?\s*(second|minute|hour|day)s?\s*$")


@dataclass(frozen=True)
class Limit:
    count: int
    window_seconds: int


def parse_limit(spec: str) -> Limit:
    """`10/minute`, `5/15minutes`, `600/hour` -> Limit. Limits live in configuration."""
    match = _PATTERN.match(spec)
    if not match or int(match.group(1)) < 1:
        raise ValueError(f"invalid rate limit {spec!r}; expected e.g. '10/minute' or '5/15minutes'")
    amount = int(match.group(2) or 1)
    return Limit(count=int(match.group(1)), window_seconds=amount * _UNITS[match.group(3)])


@dataclass(frozen=True)
class RateResult:
    allowed: bool
    limit: int
    remaining: int
    retry_after: int  # seconds until the window resets (meaningful when not allowed)
    degraded: bool = False  # True when Redis was unreachable and the check was skipped


class RateLimiter:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    @staticmethod
    def _key(scope: str, identity: str, window: int) -> str:
        # Identities (emails, IPs) are hashed so no personal data sits in Redis keys.
        digest = hashlib.sha256(identity.encode()).hexdigest()[:32]
        return f"rl:{scope}:{window}:{digest}"

    async def hit(self, scope: str, identity: str, limit: Limit) -> RateResult:
        key = self._key(scope, identity, limit.window_seconds)
        try:
            pipe = self._redis.pipeline(transaction=True)
            pipe.incr(key)
            pipe.expire(key, limit.window_seconds, nx=True)
            pipe.ttl(key)
            count, _, ttl = await pipe.execute()
            if ttl < 0:  # a key without expiry would block forever; repair it
                await self._redis.expire(key, limit.window_seconds)
                ttl = limit.window_seconds
        except (RedisError, OSError) as exc:
            logger.warning("rate limiter unavailable, failing open: %s", type(exc).__name__)
            return RateResult(True, limit.count, limit.count, 0, degraded=True)
        allowed = int(count) <= limit.count
        return RateResult(
            allowed=allowed,
            limit=limit.count,
            remaining=max(0, limit.count - int(count)),
            retry_after=0 if allowed else max(1, int(ttl)),
        )
