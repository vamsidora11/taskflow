"""The audit trail: who can read it, what it records, and that it is written with the change."""

import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.services.audit import AuditService
from tests.helpers import (
    COOKIE,
    PASSWORD,
    Mailbox,
    OrgSetup,
    create_org,
    make_board,
    make_task,
    signup,
    unique_email,
)


@pytest.fixture
async def org(api: AsyncClient, admin_engine: AsyncEngine) -> OrgSetup:
    return await create_org(api, admin_engine)


async def audit(api: AsyncClient, actor: Any, **params: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        query = {**params, **({"cursor": cursor} if cursor else {})}
        resp = await api.get("/api/v1/audit-logs", params=query, headers=actor.headers)
        assert resp.status_code == 200, resp.text
        items += resp.json()["items"]
        cursor = resp.json()["next_cursor"]
        if cursor is None:
            return items


async def db_count(engine: AsyncEngine, action: str, **where: Any) -> int:
    clauses = "".join(f" AND {k} = :{k}" for k in where)
    async with engine.connect() as conn:
        return int(
            (
                await conn.execute(
                    text(f"SELECT count(*) FROM audit_logs WHERE action = :a{clauses}"),
                    {"a": action, **where},
                )
            ).scalar_one()
        )


# --- reading ---------------------------------------------------------------------------------


@pytest.mark.parametrize(("role", "status"), [("admin", 200), ("manager", 200), ("member", 403)])
async def test_only_admins_and_managers_read_the_log(
    api: AsyncClient, org: OrgSetup, role: str, status: int
) -> None:
    resp = await api.get("/api/v1/audit-logs", headers=org.actor(role).headers)
    assert resp.status_code == status


async def test_the_log_is_newest_first_with_actor_ip_and_request_id(
    api: AsyncClient, org: OrgSetup
) -> None:
    board = await make_board(api, org.manager, "Audited")
    resp = await api.patch(
        f"/api/v1/boards/{board['id']}",
        json={"name": "Renamed"},
        headers={**org.manager.headers, "X-Request-ID": "trace-42"},
    )
    assert resp.status_code == 200
    entries = await audit(api, org.admin)
    assert [e["id"] for e in entries] == sorted((e["id"] for e in entries), reverse=True)
    newest = entries[0]
    assert newest["action"] == "board.updated"
    assert newest["entity_type"] == "board"
    assert newest["entity_id"] == board["id"]
    assert newest["actor_user_id"] == org.manager.user_id
    assert newest["request_id"] == "trace-42"  # correlates with logs and the response header
    assert newest["ip_address"] == "127.0.0.1"
    assert newest["metadata"]["changes"] == {"name": {"from": "Audited", "to": "Renamed"}}


async def test_diffs_hold_only_the_fields_that_changed(api: AsyncClient, org: OrgSetup) -> None:
    board = await make_board(api, org.admin)
    task = await make_task(
        api, org.admin, board["id"], "T", description="long " * 100, priority="low"
    )
    await api.patch(
        f"/api/v1/tasks/{task['id']}",
        json={"priority": "urgent", "title": "T"},
        headers=org.admin.headers,
    )
    [entry] = await audit(api, org.admin, action="task.updated")
    assert entry["metadata"]["changes"] == {"priority": {"from": "low", "to": "urgent"}}
    assert "long" not in str(entry["metadata"])


async def test_filters_combine_and_paginate(api: AsyncClient, org: OrgSetup) -> None:
    board = await make_board(api, org.admin)
    tasks = [await make_task(api, org.manager, board["id"], f"T{i}") for i in range(4)]
    await api.delete(f"/api/v1/tasks/{tasks[0]['id']}", headers=org.manager.headers)

    created = await audit(api, org.admin, action="task.created")
    assert len(created) == 4
    assert {e["actor_user_id"] for e in created} == {org.manager.user_id}
    by_admin = await audit(api, org.admin, actor_user_id=org.admin.user_id, entity_type="task")
    assert by_admin == []
    only_tasks = await audit(api, org.admin, entity_type="task")
    assert {e["entity_type"] for e in only_tasks} == {"task"}
    assert len(only_tasks) == 5  # four created, one deleted

    seen: list[int] = []
    cursor: str | None = None
    while True:
        params: dict[str, Any] = {"limit": 2, **({"cursor": cursor} if cursor else {})}
        body = (
            await api.get("/api/v1/audit-logs", params=params, headers=org.admin.headers)
        ).json()
        assert len(body["items"]) <= 2
        seen += [e["id"] for e in body["items"]]
        cursor = body["next_cursor"]
        if cursor is None:
            break
    everything = await audit(api, org.admin)
    assert seen == [e["id"] for e in everything]
    assert len(seen) == len(set(seen))


async def test_date_range_filters(api: AsyncClient, org: OrgSetup) -> None:
    await make_board(api, org.admin)
    future = await audit(api, org.admin, created_from="2999-01-01T00:00:00Z")
    past = await audit(api, org.admin, created_to="2000-01-01T00:00:00Z")
    window = await audit(
        api, org.admin, created_from="2000-01-01T00:00:00Z", created_to="2999-01-01T00:00:00Z"
    )
    assert (future, past) == ([], [])
    assert len(window) >= 1


@pytest.mark.parametrize(
    "params", [{"limit": 0}, {"created_from": "yesterday"}, {"actor_user_id": "x"}]
)
async def test_bad_audit_params_are_422(
    api: AsyncClient, org: OrgSetup, params: dict[str, Any]
) -> None:
    resp = await api.get("/api/v1/audit-logs", params=params, headers=org.admin.headers)
    assert resp.status_code == 422


async def test_a_malformed_cursor_is_422(api: AsyncClient, org: OrgSetup) -> None:
    resp = await api.get("/api/v1/audit-logs", params={"cursor": "junk"}, headers=org.admin.headers)
    assert (resp.status_code, resp.json()["error"]["code"]) == (422, "INVALID_CURSOR")


async def test_one_organization_never_sees_anothers_log(
    api: AsyncClient, admin_engine: AsyncEngine, org: OrgSetup
) -> None:
    other = await create_org(api, admin_engine)
    await make_board(api, other.admin, "Secret board")
    mine = await audit(api, org.admin)
    assert "Secret board" not in str(mine)
    assert other.org_id not in str(mine)


# --- exactly one row per action ------------------------------------------------------------------

Op = Callable[[AsyncClient, OrgSetup, AsyncEngine, Mailbox], Awaitable[dict[str, Any]]]


async def _task_ctx(api: AsyncClient, org: OrgSetup) -> tuple[dict[str, Any], dict[str, Any]]:
    board = await make_board(api, org.admin)
    return board, await make_task(api, org.admin, board["id"], "T")


async def op_login(
    api: AsyncClient, org: OrgSetup, db: AsyncEngine, mail: Mailbox
) -> dict[str, Any]:
    api.cookies.clear()
    r = await api.post("/api/v1/auth/login", json={"email": org.admin.email, "password": PASSWORD})
    assert r.status_code == 200
    return {"organization_id": org.org_id, "actor_user_id": org.admin.user_id}


async def op_login_failed(
    api: AsyncClient, org: OrgSetup, db: AsyncEngine, mail: Mailbox
) -> dict[str, Any]:
    r = await api.post(
        "/api/v1/auth/login", json={"email": org.admin.email, "password": "wrong password!!"}
    )
    assert r.status_code == 401
    return {"actor_user_id": org.admin.user_id}


async def op_reuse(
    api: AsyncClient, org: OrgSetup, db: AsyncEngine, mail: Mailbox
) -> dict[str, Any]:
    api.cookies.clear()
    await api.post("/api/v1/auth/login", json={"email": org.admin.email, "password": PASSWORD})
    stolen = api.cookies[COOKIE]
    await api.post("/api/v1/auth/refresh")
    async with AsyncClient(
        transport=api._transport,
        base_url="https://test",
        headers={"Cookie": f"{COOKIE}={stolen}"},
    ) as attacker:
        assert (await attacker.post("/api/v1/auth/refresh")).status_code == 401
    return {"organization_id": org.org_id, "actor_user_id": org.admin.user_id}


async def op_org_updated(
    api: AsyncClient, org: OrgSetup, db: AsyncEngine, mail: Mailbox
) -> dict[str, Any]:
    assert (
        await api.patch("/api/v1/org", json={"name": "New Name"}, headers=org.admin.headers)
    ).status_code == 200
    return {"organization_id": org.org_id}


async def op_invited(
    api: AsyncClient, org: OrgSetup, db: AsyncEngine, mail: Mailbox
) -> dict[str, Any]:
    r = await api.post(
        "/api/v1/org/invitations",
        json={"email": unique_email("inv"), "role": "member"},
        headers=org.admin.headers,
    )
    assert r.status_code == 201
    return {"organization_id": org.org_id}


async def op_joined(
    api: AsyncClient, org: OrgSetup, db: AsyncEngine, mail: Mailbox
) -> dict[str, Any]:
    email = unique_email("join")
    await api.post(
        "/api/v1/org/invitations",
        json={"email": email, "role": "member"},
        headers=org.admin.headers,
    )
    r = await api.post(
        f"/api/v1/org/invitations/{mail.token_for(email)}/accept",
        json={"password": PASSWORD, "full_name": "J"},
    )
    assert r.status_code == 200
    return {"organization_id": org.org_id}


async def op_role_changed(
    api: AsyncClient, org: OrgSetup, db: AsyncEngine, mail: Mailbox
) -> dict[str, Any]:
    r = await api.patch(
        f"/api/v1/org/members/{org.member.user_id}",
        json={"role": "manager"},
        headers=org.admin.headers,
    )
    assert r.status_code == 200
    return {"organization_id": org.org_id}


async def op_removed(
    api: AsyncClient, org: OrgSetup, db: AsyncEngine, mail: Mailbox
) -> dict[str, Any]:
    assert (
        await api.delete(f"/api/v1/org/members/{org.member.user_id}", headers=org.admin.headers)
    ).status_code == 204
    return {"organization_id": org.org_id}


async def op_board_created(
    api: AsyncClient, org: OrgSetup, db: AsyncEngine, mail: Mailbox
) -> dict[str, Any]:
    await make_board(api, org.manager)
    return {"organization_id": org.org_id}


async def op_board_updated(
    api: AsyncClient, org: OrgSetup, db: AsyncEngine, mail: Mailbox
) -> dict[str, Any]:
    board = await make_board(api, org.manager)
    r = await api.patch(
        f"/api/v1/boards/{board['id']}", json={"name": "Z"}, headers=org.manager.headers
    )
    assert r.status_code == 200
    return {"organization_id": org.org_id}


async def op_board_archived(
    api: AsyncClient, org: OrgSetup, db: AsyncEngine, mail: Mailbox
) -> dict[str, Any]:
    board = await make_board(api, org.manager)
    assert (
        await api.delete(f"/api/v1/boards/{board['id']}", headers=org.manager.headers)
    ).status_code == 204
    return {"organization_id": org.org_id}


async def op_task_created(
    api: AsyncClient, org: OrgSetup, db: AsyncEngine, mail: Mailbox
) -> dict[str, Any]:
    await _task_ctx(api, org)
    return {"organization_id": org.org_id}


async def op_task_updated(
    api: AsyncClient, org: OrgSetup, db: AsyncEngine, mail: Mailbox
) -> dict[str, Any]:
    _, task = await _task_ctx(api, org)
    assert (
        await api.patch(
            f"/api/v1/tasks/{task['id']}", json={"title": "T2"}, headers=org.admin.headers
        )
    ).status_code == 200
    return {"organization_id": org.org_id}


async def op_task_moved(
    api: AsyncClient, org: OrgSetup, db: AsyncEngine, mail: Mailbox
) -> dict[str, Any]:
    board, task = await _task_ctx(api, org)
    r = await api.post(
        f"/api/v1/tasks/{task['id']}/move",
        json={"column_id": board["columns"][1]["id"], "position": 0},
        headers=org.admin.headers,
    )
    assert r.status_code == 200
    return {"organization_id": org.org_id}


async def op_task_deleted(
    api: AsyncClient, org: OrgSetup, db: AsyncEngine, mail: Mailbox
) -> dict[str, Any]:
    _, task = await _task_ctx(api, org)
    assert (
        await api.delete(f"/api/v1/tasks/{task['id']}", headers=org.admin.headers)
    ).status_code == 204
    return {"organization_id": org.org_id}


async def op_comment_created(
    api: AsyncClient, org: OrgSetup, db: AsyncEngine, mail: Mailbox
) -> dict[str, Any]:
    _, task = await _task_ctx(api, org)
    assert (
        await api.post(
            f"/api/v1/tasks/{task['id']}/comments", json={"body": "hi"}, headers=org.member.headers
        )
    ).status_code == 201
    return {"organization_id": org.org_id}


async def op_comment_deleted(
    api: AsyncClient, org: OrgSetup, db: AsyncEngine, mail: Mailbox
) -> dict[str, Any]:
    _, task = await _task_ctx(api, org)
    c = (
        await api.post(
            f"/api/v1/tasks/{task['id']}/comments", json={"body": "hi"}, headers=org.member.headers
        )
    ).json()
    assert (
        await api.delete(f"/api/v1/comments/{c['id']}", headers=org.member.headers)
    ).status_code == 204
    return {"organization_id": org.org_id}


OPS: dict[str, Op] = {
    "auth.login": op_login,
    "auth.login_failed": op_login_failed,
    "auth.refresh_reuse_detected": op_reuse,
    "org.updated": op_org_updated,
    "member.invited": op_invited,
    "member.joined": op_joined,
    "member.role_changed": op_role_changed,
    "member.removed": op_removed,
    "board.created": op_board_created,
    "board.updated": op_board_updated,
    "board.archived": op_board_archived,
    "task.created": op_task_created,
    "task.updated": op_task_updated,
    "task.moved": op_task_moved,
    "task.deleted": op_task_deleted,
    "comment.created": op_comment_created,
    "comment.deleted": op_comment_deleted,
}


@pytest.mark.parametrize("action", list(OPS))
async def test_each_action_writes_exactly_one_audit_row(
    api: AsyncClient, admin_engine: AsyncEngine, mailbox: Mailbox, org: OrgSetup, action: str
) -> None:
    """The setup each operation does (creating a board, a task) writes different actions, so
    the count of `action` rises by exactly one across the whole operation."""
    probe = (
        {"actor_user_id": org.admin.user_id}
        if action == "auth.login_failed"
        else {"organization_id": org.org_id}
    )
    before = await db_count(admin_engine, action, **probe)
    await OPS[action](api, org, admin_engine, mailbox)
    assert await db_count(admin_engine, action, **probe) - before == 1, action


async def test_signup_records_the_organization_and_the_first_login(
    api: AsyncClient, admin_engine: AsyncEngine
) -> None:
    session = await signup(api, org="Audit Co")
    org_id = session["organization_id"]
    assert await db_count(admin_engine, "org.created", organization_id=org_id) == 1
    assert await db_count(admin_engine, "auth.login", organization_id=org_id) == 1


async def test_operations_that_change_nothing_write_nothing(
    api: AsyncClient, admin_engine: AsyncEngine, org: OrgSetup
) -> None:
    board, task = await _task_ctx(api, org)
    await api.delete(f"/api/v1/boards/{board['id']}", headers=org.admin.headers)
    await api.delete(f"/api/v1/boards/{board['id']}", headers=org.admin.headers)  # already archived
    assert await db_count(admin_engine, "board.archived", organization_id=org.org_id) == 1

    other_board, other_task = await _task_ctx(api, org)
    await api.patch(
        f"/api/v1/tasks/{other_task['id']}", json={"title": "T"}, headers=org.admin.headers
    )  # same value
    same_slot = {"column_id": other_board["columns"][0]["id"], "position": 0}
    await api.post(
        f"/api/v1/tasks/{other_task['id']}/move", json=same_slot, headers=org.admin.headers
    )
    await api.patch(
        f"/api/v1/org/members/{org.admin.user_id}",
        json={"role": "admin"},
        headers=org.admin.headers,
    )
    for action in ("task.updated", "task.moved", "member.role_changed"):
        assert await db_count(admin_engine, action, organization_id=org.org_id) == 0, action


async def test_failed_and_forbidden_requests_write_nothing(
    api: AsyncClient, admin_engine: AsyncEngine, org: OrgSetup
) -> None:
    board, task = await _task_ctx(api, org)
    await api.patch(
        f"/api/v1/org/members/{org.admin.user_id}",
        json={"role": "member"},
        headers=org.admin.headers,
    )  # last admin
    await api.patch(
        f"/api/v1/tasks/{task['id']}", json={"title": "x"}, headers=org.member.headers
    )  # not theirs
    await api.delete(f"/api/v1/tasks/{task['id']}", headers=org.member.headers)  # forbidden
    await api.post(
        f"/api/v1/boards/{board['id']}/tasks", json={"title": ""}, headers=org.admin.headers
    )  # invalid
    for action in ("member.role_changed", "task.updated", "task.deleted"):
        assert await db_count(admin_engine, action, organization_id=org.org_id) == 0, action
    assert await db_count(admin_engine, "task.created", organization_id=org.org_id) == 1


async def test_a_failed_login_is_a_system_event_hidden_from_every_organization(
    api: AsyncClient, admin_engine: AsyncEngine, org: OrgSetup
) -> None:
    await api.post(
        "/api/v1/auth/login", json={"email": unique_email("ghost"), "password": "nope nope nope"}
    )
    await api.post(
        "/api/v1/auth/login", json={"email": org.admin.email, "password": "nope nope nope"}
    )
    assert await db_count(admin_engine, "auth.login_failed") >= 2
    assert await db_count(admin_engine, "auth.login_failed", organization_id=org.org_id) == 0
    assert [e for e in await audit(api, org.admin) if e["action"] == "auth.login_failed"] == []
    async with admin_engine.connect() as conn:  # the attempted address is never stored
        stored = (
            await conn.execute(
                text(
                    "SELECT string_agg(metadata::text, ' ') FROM audit_logs "
                    "WHERE action = 'auth.login_failed'"
                )
            )
        ).scalar_one()
    assert "@example.com" not in stored
    assert "email_fingerprint" in stored


async def test_reuse_detection_is_visible_to_the_organizations_admins(
    api: AsyncClient, org: OrgSetup, admin_engine: AsyncEngine, mailbox: Mailbox
) -> None:
    await op_reuse(api, org, admin_engine, mailbox)
    entries = await audit(api, org.admin, action="auth.refresh_reuse_detected")
    assert len(entries) == 1
    assert entries[0]["actor_user_id"] == org.admin.user_id


# --- same transaction ----------------------------------------------------------------------------


async def test_if_the_audit_write_fails_the_change_is_rolled_back(
    api: AsyncClient, org: OrgSetup, monkeypatch: pytest.MonkeyPatch
) -> None:
    board = await make_board(api, org.admin)

    async def boom(self: AuditService, **kwargs: Any) -> None:
        raise RuntimeError("audit store down")

    monkeypatch.setattr(AuditService, "record", boom)
    quiet = AsyncClient(
        transport=ASGITransport(app=api._transport.app, raise_app_exceptions=False),  # type: ignore[attr-defined]
        base_url="https://test",
    )
    async with quiet:
        resp = await quiet.post(
            f"/api/v1/boards/{board['id']}/tasks",
            json={"title": "ghost"},
            headers=org.admin.headers,
        )
    assert resp.status_code == 500
    monkeypatch.undo()
    listed = await api.get(f"/api/v1/boards/{board['id']}/tasks", headers=org.admin.headers)
    assert listed.json()["items"] == []  # no task without its audit row


async def test_audit_rows_carry_the_request_id_of_the_response(
    api: AsyncClient, org: OrgSetup
) -> None:
    resp = await api.post(
        "/api/v1/boards", json={"name": "Correlated"}, headers=org.manager.headers
    )
    request_id = resp.headers["x-request-id"]
    [entry] = [
        e
        for e in await audit(api, org.admin, action="board.created")
        if e["request_id"] == request_id
    ]
    assert entry["entity_id"] == resp.json()["id"]
    assert uuid.UUID(entry["entity_id"])
