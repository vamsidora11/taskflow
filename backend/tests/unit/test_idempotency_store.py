import os
from collections.abc import AsyncIterator

import pytest
from fakeredis import FakeAsyncRedis, FakeServer
from redis.asyncio import Redis

from app.core.exceptions import (
    IdempotencyInProgressError,
    IdempotencyKeyReusedError,
    IdempotencyUnavailableError,
)
from app.services.idempotency import (
    COMPLETED_TTL_SECONDS,
    PENDING_TTL_SECONDS,
    IdempotencyStore,
    StoredResponse,
    fingerprint,
)

RESPONSE = StoredResponse(status=201, body={"id": "abc", "title": "T"})


@pytest.fixture(params=["fake", "real"])
async def redis(request: pytest.FixtureRequest) -> AsyncIterator[Redis]:
    """The same behaviour is checked against an in-memory fake and, when one is reachable
    (always in CI), a real Redis."""
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
    for key in await client.keys("idem:test:*"):
        await client.delete(key)
    await client.aclose()


SCOPE = "test:org:user"


async def test_first_request_claims_the_key_and_a_replay_returns_the_response(redis: Redis) -> None:
    store = IdempotencyStore(redis)
    assert await store.begin(SCOPE, "k1", "fp") is None
    await store.complete(SCOPE, "k1", "fp", RESPONSE)
    assert await store.begin(SCOPE, "k1", "fp") == RESPONSE


async def test_a_concurrent_duplicate_is_told_the_first_is_in_progress(redis: Redis) -> None:
    store = IdempotencyStore(redis)
    await store.begin(SCOPE, "k2", "fp")
    with pytest.raises(IdempotencyInProgressError):
        await store.begin(SCOPE, "k2", "fp")


async def test_reusing_a_key_with_a_different_request_is_rejected_in_every_state(
    redis: Redis,
) -> None:
    store = IdempotencyStore(redis)
    await store.begin(SCOPE, "k3", "fp-one")
    with pytest.raises(IdempotencyKeyReusedError):  # while pending
        await store.begin(SCOPE, "k3", "fp-two")
    await store.complete(SCOPE, "k3", "fp-one", RESPONSE)
    with pytest.raises(IdempotencyKeyReusedError):  # once completed
        await store.begin(SCOPE, "k3", "fp-two")


async def test_abort_releases_the_key_for_a_retry(redis: Redis) -> None:
    store = IdempotencyStore(redis)
    await store.begin(SCOPE, "k4", "fp")
    await store.abort(SCOPE, "k4")
    assert await store.begin(SCOPE, "k4", "fp") is None


async def test_scopes_are_independent(redis: Redis) -> None:
    store = IdempotencyStore(redis)
    assert await store.begin("test:org1:u1", "same", "fp") is None
    assert await store.begin("test:org1:u2", "same", "fp") is None
    assert await store.begin("test:org2:u1", "same", "fp") is None


async def test_ttls_and_key_hygiene(redis: Redis) -> None:
    store = IdempotencyStore(redis)
    await store.begin(SCOPE, "secret-client-key", "fp")
    [key] = await redis.keys("idem:test:*")
    assert 0 < await redis.ttl(key) <= PENDING_TTL_SECONDS
    assert b"secret-client-key" not in key  # the client's key is hashed, never stored raw
    await store.complete(SCOPE, "secret-client-key", "fp", RESPONSE)
    assert COMPLETED_TTL_SECONDS - 5 <= await redis.ttl(key) <= COMPLETED_TTL_SECONDS
    assert COMPLETED_TTL_SECONDS == 86400


async def test_redis_failures_become_a_503_style_error_not_a_crash() -> None:
    dead = Redis.from_url("redis://127.0.0.1:1/0")
    try:
        with pytest.raises(IdempotencyUnavailableError):
            await IdempotencyStore(dead).begin(SCOPE, "k", "fp")
        await IdempotencyStore(dead).complete(SCOPE, "k", "fp", RESPONSE)  # must not raise
        await IdempotencyStore(dead).abort(SCOPE, "k")  # must not raise
    finally:
        await dead.aclose()


def test_fingerprint_ignores_key_order_and_whitespace_but_not_content() -> None:
    a = fingerprint(b'{"title": "T", "priority": "high"}', "POST", "/x")
    b = fingerprint(b'{"priority":"high","title":"T"}', "POST", "/x")
    assert a == b
    assert a != fingerprint(b'{"title": "T", "priority": "low"}', "POST", "/x")
    assert a != fingerprint(b'{"title": "T", "priority": "high"}', "POST", "/y")
    assert a != fingerprint(b'{"title": "T", "priority": "high"}', "PUT", "/x")
    assert fingerprint(b"not json", "POST", "/x")  # tolerated, still deterministic
