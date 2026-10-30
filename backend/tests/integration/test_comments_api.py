import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.helpers import OrgSetup, create_org, make_board, make_task


@pytest.fixture
async def org(api: AsyncClient, admin_engine: AsyncEngine) -> OrgSetup:
    return await create_org(api, admin_engine)


@pytest.fixture
async def task(api: AsyncClient, org: OrgSetup) -> dict[str, Any]:
    board = await make_board(api, org.admin)
    return await make_task(api, org.admin, board["id"], "Discuss me")


async def comment(api: AsyncClient, actor: Any, task_id: str, body: str = "Hello") -> Any:
    return await api.post(
        f"/api/v1/tasks/{task_id}/comments", json={"body": body}, headers=actor.headers
    )


async def test_every_role_can_comment_and_the_author_is_recorded(
    api: AsyncClient, org: OrgSetup, task: dict[str, Any]
) -> None:
    for actor in (org.admin, org.manager, org.member):
        resp = await comment(api, actor, task["id"], f"From {actor.role}")
        assert resp.status_code == 201
        assert resp.json()["author_id"] == actor.user_id
        assert resp.json()["task_id"] == task["id"]
    listed = await api.get(f"/api/v1/tasks/{task['id']}/comments", headers=org.member.headers)
    assert [c["body"] for c in listed.json()["items"]] == [
        "From admin",
        "From manager",
        "From member",
    ]


@pytest.mark.parametrize("body", [None, "", "x" * 5001])
async def test_invalid_comments_are_rejected(
    api: AsyncClient, org: OrgSetup, task: dict[str, Any], body: object
) -> None:
    resp = await api.post(
        f"/api/v1/tasks/{task['id']}/comments",
        json={} if body is None else {"body": body},
        headers=org.member.headers,
    )
    assert resp.status_code == 422


async def test_comments_paginate_oldest_first(
    api: AsyncClient, org: OrgSetup, task: dict[str, Any]
) -> None:
    for i in range(5):
        await comment(api, org.member, task["id"], f"c{i}")
    seen: list[str] = []
    cursor: str | None = None
    while True:
        params: dict[str, Any] = {"limit": 2, **({"cursor": cursor} if cursor else {})}
        body = (
            await api.get(
                f"/api/v1/tasks/{task['id']}/comments", params=params, headers=org.member.headers
            )
        ).json()
        seen += [c["body"] for c in body["items"]]
        cursor = body["next_cursor"]
        if cursor is None:
            break
    assert seen == [f"c{i}" for i in range(5)]


async def test_an_author_deletes_their_own_comment_but_not_others(
    api: AsyncClient, org: OrgSetup, task: dict[str, Any]
) -> None:
    mine = (await comment(api, org.member, task["id"], "mine")).json()
    theirs = (await comment(api, org.manager, task["id"], "theirs")).json()
    denied = await api.delete(f"/api/v1/comments/{theirs['id']}", headers=org.member.headers)
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "PERMISSION_DENIED"
    assert (
        await api.delete(f"/api/v1/comments/{mine['id']}", headers=org.member.headers)
    ).status_code == 204
    remaining = (
        await api.get(f"/api/v1/tasks/{task['id']}/comments", headers=org.admin.headers)
    ).json()
    assert [c["body"] for c in remaining["items"]] == ["theirs"]


@pytest.mark.parametrize("deleter", ["manager", "admin"])
async def test_managers_and_admins_delete_anyones_comment(
    api: AsyncClient, org: OrgSetup, task: dict[str, Any], deleter: str
) -> None:
    c = (await comment(api, org.member, task["id"])).json()
    resp = await api.delete(f"/api/v1/comments/{c['id']}", headers=org.actor(deleter).headers)
    assert resp.status_code == 204


async def test_deleting_twice_or_unknown_is_404(
    api: AsyncClient, org: OrgSetup, task: dict[str, Any]
) -> None:
    c = (await comment(api, org.member, task["id"])).json()
    await api.delete(f"/api/v1/comments/{c['id']}", headers=org.member.headers)
    for cid in (c["id"], str(uuid.uuid4())):
        resp = await api.delete(f"/api/v1/comments/{cid}", headers=org.admin.headers)
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "COMMENT_NOT_FOUND"


async def test_commenting_on_a_deleted_or_unknown_task_is_404(
    api: AsyncClient, org: OrgSetup, task: dict[str, Any]
) -> None:
    await api.delete(f"/api/v1/tasks/{task['id']}", headers=org.admin.headers)
    for tid in (task["id"], str(uuid.uuid4())):
        assert (await comment(api, org.member, tid)).status_code == 404
        listed = await api.get(f"/api/v1/tasks/{tid}/comments", headers=org.member.headers)
        assert listed.status_code == 404


async def test_an_archived_board_makes_comments_read_only(
    api: AsyncClient, org: OrgSetup, task: dict[str, Any]
) -> None:
    c = (await comment(api, org.member, task["id"])).json()
    await api.delete(f"/api/v1/boards/{task['board_id']}", headers=org.admin.headers)
    blocked = await comment(api, org.member, task["id"])
    assert (blocked.status_code, blocked.json()["error"]["code"]) == (409, "BOARD_ARCHIVED")
    assert (
        await api.delete(f"/api/v1/comments/{c['id']}", headers=org.admin.headers)
    ).status_code == 409
    assert (
        await api.get(f"/api/v1/tasks/{task['id']}/comments", headers=org.member.headers)
    ).status_code == 200


async def test_comments_never_cross_organizations(
    api: AsyncClient, admin_engine: AsyncEngine, org: OrgSetup, task: dict[str, Any]
) -> None:
    c = (await comment(api, org.member, task["id"])).json()
    other = await create_org(api, admin_engine)
    h = other.admin.headers
    assert (await api.get(f"/api/v1/tasks/{task['id']}/comments", headers=h)).status_code == 404
    assert (await comment(api, other.admin, task["id"])).status_code == 404
    assert (await api.delete(f"/api/v1/comments/{c['id']}", headers=h)).status_code == 404
    still = await api.get(f"/api/v1/tasks/{task['id']}/comments", headers=org.admin.headers)
    assert len(still.json()["items"]) == 1


async def test_unauthenticated_comment_requests_are_401(api: AsyncClient) -> None:
    fake = uuid.uuid4()
    for call in (
        api.get(f"/api/v1/tasks/{fake}/comments"),
        api.post(f"/api/v1/tasks/{fake}/comments", json={"body": "x"}),
        api.delete(f"/api/v1/comments/{fake}"),
    ):
        assert (await call).status_code == 401
