import asyncio
import os
from collections.abc import AsyncIterator

import pytest
from fakeredis import FakeAsyncRedis, FakeServer
from redis.asyncio import Redis

from app.core.rate_limit import Limit, RateLimiter, parse_limit


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        ("10/minute", Limit(10, 60)),
        ("5/15minutes", Limit(5, 900)),
        ("600/minute", Limit(600, 60)),
        ("1/second", Limit(1, 1)),
        ("100/hour", Limit(100, 3600)),
        ("3/2days", Limit(3, 172800)),
        (" 7 / 30 seconds ", Limit(7, 30)),
    ],
)
def test_limits_parse(spec: str, expected: Limit) -> None:
    assert parse_limit(spec) == expected


@pytest.mark.parametrize(
    "spec", ["", "10", "ten/minute", "0/minute", "10/fortnight", "10/-1minute"]
)
def test_bad_limits_are_rejected(spec: str) -> None:
    with pytest.raises(ValueError, match="invalid rate limit"):
        parse_limit(spec)


@pytest.fixture(params=["fake", "real"])
async def redis(request: pytest.FixtureRequest) -> AsyncIterator[Redis]:
    if request.param == "fake":
        client: Redis = FakeAsyncRedis(server=FakeServer())
    else:
        client = Redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        try:
            await client.ping()
        except Exception:
            await client.aclose()
            if os.environ.get("CI"):
                raise
            pytest.skip("Redis not reachable; set REDIS_URL")
    yield client
    for key in await client.keys("rl:utest*"):
        await client.delete(key)
    await client.aclose()


async def test_requests_up_to_the_limit_pass_then_are_blocked(redis: Redis) -> None:
    limiter, limit = RateLimiter(redis), Limit(3, 60)
    results = [await limiter.hit("utest", "ip-1", limit) for _ in range(5)]
    assert [r.allowed for r in results] == [True, True, True, False, False]
    assert [r.remaining for r in results] == [2, 1, 0, 0, 0]
    assert all(r.limit == 3 for r in results)
    assert 1 <= results[3].retry_after <= 60
    assert results[0].retry_after == 0


async def test_identities_and_scopes_are_independent(redis: Redis) -> None:
    limiter, limit = RateLimiter(redis), Limit(1, 60)
    assert (await limiter.hit("utest-a", "x", limit)).allowed
    assert not (await limiter.hit("utest-a", "x", limit)).allowed
    assert (await limiter.hit("utest-a", "y", limit)).allowed  # another identity
    assert (await limiter.hit("utest-b", "x", limit)).allowed  # another scope


async def test_the_window_resets(redis: Redis) -> None:
    limiter, limit = RateLimiter(redis), Limit(1, 1)
    assert (await limiter.hit("utest-w", "x", limit)).allowed
    assert not (await limiter.hit("utest-w", "x", limit)).allowed
    await asyncio.sleep(1.2)
    assert (await limiter.hit("utest-w", "x", limit)).allowed


async def test_concurrent_hits_are_counted_atomically(redis: Redis) -> None:
    limiter, limit = RateLimiter(redis), Limit(10, 60)
    results = await asyncio.gather(*[limiter.hit("utest-c", "x", limit) for _ in range(60)])
    assert sum(r.allowed for r in results) == 10


async def test_a_key_that_lost_its_expiry_is_repaired(redis: Redis) -> None:
    limiter, limit = RateLimiter(redis), Limit(1, 60)
    await limiter.hit("utest-r", "x", limit)
    [key] = await redis.keys("rl:utest-r:*")
    await redis.persist(key)  # simulate the INCR/EXPIRE pair being interrupted
    blocked = await limiter.hit("utest-r", "x", limit)
    assert not blocked.allowed
    assert 0 < await redis.ttl(key) <= 60  # no longer immortal


async def test_identities_are_hashed_in_redis_keys(redis: Redis) -> None:
    await RateLimiter(redis).hit("utest-h", "victim@example.com", Limit(5, 60))
    [key] = await redis.keys("rl:utest-h:*")
    assert b"victim" not in key
    assert b"example.com" not in key


async def test_it_fails_open_when_redis_is_unreachable(caplog: pytest.LogCaptureFixture) -> None:
    dead = Redis.from_url("redis://127.0.0.1:1/0")
    try:
        result = await RateLimiter(dead).hit("utest", "x", Limit(1, 60))
    finally:
        await dead.aclose()
    assert result.allowed
    assert result.degraded
    assert "failing open" in caplog.text
