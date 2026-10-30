import asyncio
from typing import Any

import pytest
from httpx import AsyncClient
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.api.deps import get_redis_client
from app.services.idempotency import IdempotencyStore
from tests.helpers import OrgSetup, create_org, list_all_tasks, make_board

KEY = "6f1c2a8e-4b7d-4e9a-9d1f-2b3c4d5e6f70"


@pytest.fixture
async def org(api: AsyncClient, admin_engine: AsyncEngine) -> OrgSetup:
    return await create_org(api, admin_engine)


@pytest.fixture
async def board(api: AsyncClient, org: OrgSetup) -> dict[str, Any]:
    return await make_board(api, org.admin)


def url(board: dict[str, Any]) -> str:
    return f"/api/v1/boards/{board['id']}/tasks"


async def post(
    api: AsyncClient,
    org: OrgSetup,
    board: dict[str, Any],
    body: dict[str, Any],
    key: str | None = KEY,
    actor: str = "member",
) -> Any:
    headers = dict(org.actor(actor).headers)
    if key is not None:
        headers["Idempotency-Key"] = key
    return await api.post(url(board), json=body, headers=headers)


async def count(api: AsyncClient, org: OrgSetup, board: dict[str, Any]) -> int:
    return len(await list_all_tasks(api, org.admin, board["id"]))


async def test_a_retry_returns_the_original_response_and_creates_nothing_new(
    api: AsyncClient, org: OrgSetup, board: dict[str, Any]
) -> None:
    first = await post(api, org, board, {"title": "Once"})
    second = await post(api, org, board, {"title": "Once"})
    assert first.status_code == second.status_code == 201
    assert second.json() == first.json()
    assert "idempotent-replay" not in first.headers
    assert second.headers["idempotent-replay"] == "true"
    assert await count(api, org, board) == 1


async def test_body_key_order_does_not_matter(
    api: AsyncClient, org: OrgSetup, board: dict[str, Any]
) -> None:
    first = await post(api, org, board, {"title": "T", "priority": "high"})
    second = await post(api, org, board, {"priority": "high", "title": "T"})
    assert second.json() == first.json()
    assert await count(api, org, board) == 1


async def test_reusing_a_key_with_a_different_payload_is_409(
    api: AsyncClient, org: OrgSetup, board: dict[str, Any]
) -> None:
    await post(api, org, board, {"title": "Original"})
    resp = await post(api, org, board, {"title": "Different"})
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    assert await count(api, org, board) == 1


async def test_requests_without_a_key_are_never_deduplicated(
    api: AsyncClient, org: OrgSetup, board: dict[str, Any]
) -> None:
    await post(api, org, board, {"title": "Same"}, key=None)
    await post(api, org, board, {"title": "Same"}, key=None)
    assert await count(api, org, board) == 2


async def test_the_key_is_scoped_to_board_user_and_organization(
    api: AsyncClient, admin_engine: AsyncEngine, org: OrgSetup, board: dict[str, Any]
) -> None:
    other_board = await make_board(api, org.admin, "Second")
    a = await post(api, org, board, {"title": "T"})
    b = await post(api, org, other_board, {"title": "T"})  # same key, different board
    c = await post(api, org, board, {"title": "T"}, actor="manager")  # same key, different user
    stranger = await create_org(api, admin_engine)
    stranger_board = await make_board(api, stranger.admin)
    d = await api.post(
        url(stranger_board),
        json={"title": "T"},
        headers={**stranger.admin.headers, "Idempotency-Key": KEY},
    )  # same key, different organization
    assert [r.status_code for r in (a, b, c, d)] == [201] * 4
    assert len({r.json()["id"] for r in (a, b, c, d)}) == 4
    assert all("idempotent-replay" not in r.headers for r in (a, b, c, d))


@pytest.mark.parametrize("key", ["", "k" * 129])
async def test_an_empty_or_oversized_key_is_422(
    api: AsyncClient, org: OrgSetup, board: dict[str, Any], key: str
) -> None:
    resp = await post(api, org, board, {"title": "T"}, key=key)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"
    assert await count(api, org, board) == 0


async def test_a_key_of_128_characters_is_fine(
    api: AsyncClient, org: OrgSetup, board: dict[str, Any]
) -> None:
    assert (await post(api, org, board, {"title": "T"}, key="k" * 128)).status_code == 201


async def test_a_failed_request_releases_its_key_so_a_retry_can_succeed(
    api: AsyncClient, org: OrgSetup, board: dict[str, Any]
) -> None:
    await api.delete(f"/api/v1/boards/{board['id']}", headers=org.admin.headers)  # archive
    failed = await post(api, org, board, {"title": "T"})
    assert failed.status_code == 409
    assert failed.json()["error"]["code"] == "BOARD_ARCHIVED"

    await api.patch(
        f"/api/v1/boards/{board['id']}", json={"is_archived": False}, headers=org.admin.headers
    )
    retry = await post(api, org, board, {"title": "T"})
    assert retry.status_code == 201
    assert "idempotent-replay" not in retry.headers  # a real creation, not a stored error


async def test_a_validation_failure_does_not_poison_the_key(
    api: AsyncClient, org: OrgSetup, board: dict[str, Any]
) -> None:
    assert (await post(api, org, board, {"title": ""})).status_code == 422
    assert (await post(api, org, board, {"title": "Fixed"})).status_code == 201


async def test_concurrent_duplicates_create_exactly_one_task(
    api: AsyncClient, org: OrgSetup, board: dict[str, Any]
) -> None:
    results = await asyncio.gather(*[post(api, org, board, {"title": "Race"}) for _ in range(5)])
    statuses = [r.status_code for r in results]
    assert set(statuses) <= {201, 409}
    assert 201 in statuses
    assert {r.json()["error"]["code"] for r in results if r.status_code == 409} <= {
        "IDEMPOTENCY_IN_PROGRESS"
    }
    assert len({r.json()["id"] for r in results if r.status_code == 201}) == 1
    assert await count(api, org, board) == 1


async def test_the_response_is_stored_only_after_the_task_is_committed(
    api: AsyncClient,
    admin_engine: AsyncEngine,
    org: OrgSetup,
    board: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the stored response were written before the commit, a failed commit would leave a
    replayable 201 for a task that never existed."""
    visible_at_store_time: list[int] = []
    real_complete = IdempotencyStore.complete

    async def spy(self: IdempotencyStore, *args: Any, **kwargs: Any) -> None:
        async with admin_engine.connect() as conn:
            n = (
                await conn.execute(
                    text("SELECT count(*) FROM tasks WHERE board_id = :b"), {"b": board["id"]}
                )
            ).scalar_one()
        visible_at_store_time.append(int(n))
        await real_complete(self, *args, **kwargs)

    monkeypatch.setattr(IdempotencyStore, "complete", spy)
    assert (await post(api, org, board, {"title": "T"})).status_code == 201
    assert visible_at_store_time == [1]


async def test_the_key_is_hashed_and_expires_in_24_hours(
    api: AsyncClient, redis_client: Redis, org: OrgSetup, board: dict[str, Any]
) -> None:
    await post(api, org, board, {"title": "T"})
    [key] = await redis_client.keys("idem:*")
    assert KEY.encode() not in key
    assert 86300 <= await redis_client.ttl(key) <= 86400


async def test_an_unauthenticated_request_never_touches_redis(
    api: AsyncClient, redis_client: Redis, board: dict[str, Any]
) -> None:
    resp = await api.post(url(board), json={"title": "T"}, headers={"Idempotency-Key": KEY})
    assert resp.status_code == 401
    assert await redis_client.keys("idem:*") == []


async def test_when_redis_is_down_a_keyed_request_is_refused_but_an_unkeyed_one_works(
    api: AsyncClient, org: OrgSetup, board: dict[str, Any]
) -> None:
    dead = Redis.from_url("redis://127.0.0.1:1/0")
    api._transport.app.dependency_overrides[get_redis_client] = lambda: dead  # type: ignore[attr-defined]
    try:
        keyed = await post(api, org, board, {"title": "T"})
        assert keyed.status_code == 503
        assert keyed.json()["error"]["code"] == "IDEMPOTENCY_UNAVAILABLE"
        unkeyed = await post(api, org, board, {"title": "T"}, key=None)
        assert unkeyed.status_code == 201
    finally:
        await dead.aclose()
    assert await count(api, org, board) == 1  # only the unkeyed one was created


async def test_a_replay_survives_the_task_being_deleted(
    api: AsyncClient, org: OrgSetup, board: dict[str, Any]
) -> None:
    first = await post(api, org, board, {"title": "T"})
    await api.delete(f"/api/v1/tasks/{first.json()['id']}", headers=org.admin.headers)
    replay = await post(api, org, board, {"title": "T"})
    assert replay.json() == first.json()  # the contract is "same response", not "same state"
    assert await count(api, org, board) == 0
