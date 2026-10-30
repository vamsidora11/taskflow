"""Cross-tenant isolation for boards, columns and tasks: another organization's resources are
indistinguishable from resources that do not exist (404), never 403 (PLAN.md section 4)."""

import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.helpers import OrgSetup, create_org, list_all_tasks, make_board, make_task


@pytest.fixture
async def two_orgs(
    api: AsyncClient, admin_engine: AsyncEngine
) -> tuple[OrgSetup, OrgSetup, dict[str, Any], dict[str, Any]]:
    mine = await create_org(api, admin_engine)
    theirs = await create_org(api, admin_engine)
    their_board = await make_board(api, theirs.admin, "Theirs")
    their_task = await make_task(api, theirs.admin, their_board["id"], "Secret plan")
    return mine, theirs, their_board, their_task


async def test_every_endpoint_hides_another_organizations_resources(
    api: AsyncClient, two_orgs: tuple[OrgSetup, OrgSetup, dict[str, Any], dict[str, Any]]
) -> None:
    mine, _theirs, board, task = two_orgs
    h = mine.admin.headers  # the strongest role in the wrong organization
    column = board["columns"][0]["id"]
    attempts = {
        "get board": await api.get(f"/api/v1/boards/{board['id']}", headers=h),
        "patch board": await api.patch(
            f"/api/v1/boards/{board['id']}", json={"name": "x"}, headers=h
        ),
        "archive board": await api.delete(f"/api/v1/boards/{board['id']}", headers=h),
        "add column": await api.post(
            f"/api/v1/boards/{board['id']}/columns", json={"name": "x"}, headers=h
        ),
        "patch column": await api.patch(f"/api/v1/columns/{column}", json={"name": "x"}, headers=h),
        "delete column": await api.delete(
            f"/api/v1/columns/{board['columns'][2]['id']}", headers=h
        ),
        "list tasks": await api.get(f"/api/v1/boards/{board['id']}/tasks", headers=h),
        "create task": await api.post(
            f"/api/v1/boards/{board['id']}/tasks", json={"title": "x"}, headers=h
        ),
        "get task": await api.get(f"/api/v1/tasks/{task['id']}", headers=h),
        "patch task": await api.patch(
            f"/api/v1/tasks/{task['id']}", json={"title": "x"}, headers=h
        ),
        "delete task": await api.delete(f"/api/v1/tasks/{task['id']}", headers=h),
        "move task": await api.post(
            f"/api/v1/tasks/{task['id']}/move", json={"column_id": column, "position": 0}, headers=h
        ),
    }
    assert {name: r.status_code for name, r in attempts.items()} == dict.fromkeys(attempts, 404)
    # The answer is the same one a nonexistent id would get, so existence is not revealed.
    ghost = await api.get(f"/api/v1/boards/{uuid.uuid4()}", headers=h)
    assert attempts["get board"].json()["error"]["code"] == ghost.json()["error"]["code"]
    assert attempts["get board"].json()["error"]["message"] == ghost.json()["error"]["message"]


async def test_nothing_was_changed_by_the_attempts(
    api: AsyncClient, two_orgs: tuple[OrgSetup, OrgSetup, dict[str, Any], dict[str, Any]]
) -> None:
    mine, theirs, board, task = two_orgs
    h = mine.admin.headers
    await api.patch(f"/api/v1/boards/{board['id']}", json={"name": "pwned"}, headers=h)
    await api.delete(f"/api/v1/boards/{board['id']}", headers=h)
    await api.patch(f"/api/v1/tasks/{task['id']}", json={"title": "pwned"}, headers=h)
    await api.delete(f"/api/v1/tasks/{task['id']}", headers=h)
    still_board = (
        await api.get(f"/api/v1/boards/{board['id']}", headers=theirs.admin.headers)
    ).json()
    still_task = (await api.get(f"/api/v1/tasks/{task['id']}", headers=theirs.admin.headers)).json()
    assert (still_board["name"], still_board["is_archived"]) == ("Theirs", False)
    assert still_task["title"] == "Secret plan"


async def test_lists_never_include_another_organizations_rows(
    api: AsyncClient, two_orgs: tuple[OrgSetup, OrgSetup, dict[str, Any], dict[str, Any]]
) -> None:
    mine, _theirs, their_board, their_task = two_orgs
    my_board = await make_board(api, mine.admin, "Mine")
    await make_task(api, mine.admin, my_board["id"], "Mine")
    boards = (
        await api.get(
            "/api/v1/boards", params={"include_archived": True}, headers=mine.admin.headers
        )
    ).json()
    assert [b["id"] for b in boards["items"]] == [my_board["id"]]
    tasks = await list_all_tasks(api, mine.admin, my_board["id"])
    assert their_task["id"] not in {t["id"] for t in tasks}
    # Filtering by a foreign id yields nothing rather than leaking rows.
    leak = await list_all_tasks(
        api, mine.admin, my_board["id"], column_id=their_board["columns"][0]["id"]
    )
    assert leak == []


async def test_a_task_cannot_be_moved_into_or_created_in_a_foreign_column(
    api: AsyncClient, two_orgs: tuple[OrgSetup, OrgSetup, dict[str, Any], dict[str, Any]]
) -> None:
    mine, theirs, their_board, _ = two_orgs
    my_board = await make_board(api, mine.admin, "Mine")
    mine_task = await make_task(api, mine.admin, my_board["id"], "Mine")
    foreign_column = their_board["columns"][0]["id"]

    moved = await api.post(
        f"/api/v1/tasks/{mine_task['id']}/move",
        json={"column_id": foreign_column, "position": 0},
        headers=mine.admin.headers,
    )
    created = await api.post(
        f"/api/v1/boards/{my_board['id']}/tasks",
        json={"title": "x", "column_id": foreign_column},
        headers=mine.admin.headers,
    )
    assert (moved.status_code, created.status_code) == (404, 404)
    assert len(await list_all_tasks(api, theirs.admin, their_board["id"])) == 1


async def test_a_foreign_user_cannot_be_assigned(
    api: AsyncClient, two_orgs: tuple[OrgSetup, OrgSetup, dict[str, Any], dict[str, Any]]
) -> None:
    mine, theirs, _, _ = two_orgs
    board = await make_board(api, mine.admin)
    resp = await api.post(
        f"/api/v1/boards/{board['id']}/tasks",
        json={"title": "x", "assignee_id": theirs.admin.user_id},
        headers=mine.admin.headers,
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "INVALID_ASSIGNEE"


async def test_the_database_alone_refuses_cross_tenant_task_access(
    api: AsyncClient,
    admin_engine: AsyncEngine,
    app_engine: AsyncEngine,
    two_orgs: tuple[OrgSetup, OrgSetup, dict[str, Any], dict[str, Any]],
) -> None:
    """Even if application code forgot its organization filter, RLS would stop the leak."""
    mine, _theirs, _board, task = two_orgs
    async with app_engine.begin() as conn:
        await conn.execute(
            text("SELECT set_config('app.current_org_id', :o, true)"), {"o": mine.org_id}
        )
        rows = (
            await conn.execute(text("SELECT id FROM tasks WHERE id = :i"), {"i": task["id"]})
        ).all()
        updated = await conn.execute(
            text("UPDATE tasks SET title = 'pwned' WHERE id = :i"), {"i": task["id"]}
        )
    assert rows == []
    assert updated.rowcount == 0
    async with admin_engine.connect() as conn:
        title = (
            await conn.execute(text("SELECT title FROM tasks WHERE id = :i"), {"i": task["id"]})
        ).scalar_one()
    assert title == "Secret plan"
