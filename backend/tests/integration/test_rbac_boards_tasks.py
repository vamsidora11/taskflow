"""PLAN.md section 5 matrix, end to end, for the board and task endpoints.

The allowed roles below are written out by hand from the plan's table, independently of
`app/core/permissions.py`, so a wrong mapping there cannot also hide here.
"""

import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.helpers import Actor, OrgSetup, create_org, make_board, make_task

ADMIN, MANAGER, MEMBER = "admin", "manager", "member"
EVERYONE = {ADMIN, MANAGER, MEMBER}
MANAGERS_UP = {ADMIN, MANAGER}

# endpoint -> (roles allowed through authorization, status when allowed)
MATRIX: dict[str, tuple[set[str], int]] = {
    "list_boards": (EVERYONE, 200),  # View boards and tasks
    "get_board": (EVERYONE, 200),
    "create_board": (MANAGERS_UP, 201),  # Create / archive boards
    "update_board": (MANAGERS_UP, 200),
    "archive_board": (MANAGERS_UP, 204),
    "restore_board": (MANAGERS_UP, 200),
    "create_column": (MANAGERS_UP, 201),
    "update_column": (MANAGERS_UP, 200),
    "delete_column": (MANAGERS_UP, 204),
    "list_tasks": (EVERYONE, 200),
    "get_task": (EVERYONE, 200),
    "create_task": (EVERYONE, 201),  # Create tasks
    "edit_own_task": (EVERYONE, 200),  # Edit tasks assigned to self
    "move_own_task": (EVERYONE, 200),
    "edit_any_task": (MANAGERS_UP, 200),  # Edit any task
    "move_any_task": (MANAGERS_UP, 200),
    "delete_task": (MANAGERS_UP, 204),  # Delete tasks
}


@pytest.fixture
async def org(api: AsyncClient, admin_engine: AsyncEngine) -> OrgSetup:
    return await create_org(api, admin_engine)


async def call(
    api: AsyncClient, org: OrgSetup, endpoint: str, actor: Actor, board: dict[str, Any]
) -> int:
    h = actor.headers
    b = f"/api/v1/boards/{board['id']}"
    todo, doing = board["columns"][0]["id"], board["columns"][1]["id"]
    own = await make_task(api, org.admin, board["id"], "own", assignee_id=actor.user_id)
    other = await make_task(api, org.admin, board["id"], "other", assignee_id=org.admin.user_id)
    if endpoint == "list_boards":
        r = await api.get("/api/v1/boards", headers=h)
    elif endpoint == "get_board":
        r = await api.get(b, headers=h)
    elif endpoint == "create_board":
        r = await api.post("/api/v1/boards", json={"name": "New"}, headers=h)
    elif endpoint == "update_board":
        r = await api.patch(b, json={"name": "Renamed"}, headers=h)
    elif endpoint == "archive_board":
        r = await api.delete(b, headers=h)
    elif endpoint == "restore_board":
        await api.delete(b, headers=org.admin.headers)
        r = await api.patch(b, json={"is_archived": False}, headers=h)
    elif endpoint == "create_column":
        r = await api.post(f"{b}/columns", json={"name": "Extra"}, headers=h)
    elif endpoint == "update_column":
        r = await api.patch(f"/api/v1/columns/{todo}", json={"name": "Renamed"}, headers=h)
    elif endpoint == "delete_column":
        r = await api.delete(f"/api/v1/columns/{board['columns'][2]['id']}", headers=h)
    elif endpoint == "list_tasks":
        r = await api.get(f"{b}/tasks", headers=h)
    elif endpoint == "get_task":
        r = await api.get(f"/api/v1/tasks/{other['id']}", headers=h)
    elif endpoint == "create_task":
        r = await api.post(f"{b}/tasks", json={"title": "New"}, headers=h)
    elif endpoint == "edit_own_task":
        r = await api.patch(f"/api/v1/tasks/{own['id']}", json={"title": "Edited"}, headers=h)
    elif endpoint == "move_own_task":
        r = await api.post(
            f"/api/v1/tasks/{own['id']}/move", json={"column_id": doing, "position": 0}, headers=h
        )
    elif endpoint == "edit_any_task":
        r = await api.patch(f"/api/v1/tasks/{other['id']}", json={"title": "Edited"}, headers=h)
    elif endpoint == "move_any_task":
        r = await api.post(
            f"/api/v1/tasks/{other['id']}/move", json={"column_id": doing, "position": 0}, headers=h
        )
    elif endpoint == "delete_task":
        r = await api.delete(f"/api/v1/tasks/{own['id']}", headers=h)
    else:
        raise AssertionError(endpoint)
    return int(r.status_code)


@pytest.mark.parametrize("role", [ADMIN, MANAGER, MEMBER])
@pytest.mark.parametrize("endpoint", list(MATRIX))
async def test_matrix(api: AsyncClient, org: OrgSetup, endpoint: str, role: str) -> None:
    allowed, ok_status = MATRIX[endpoint]
    board = await make_board(api, org.admin)
    status = await call(api, org, endpoint, org.actor(role), board)
    assert status == (ok_status if role in allowed else 403), f"{role} {endpoint}"


async def test_restoring_a_board_needs_the_archive_permission_not_just_edit(
    api: AsyncClient, org: OrgSetup
) -> None:
    board = await make_board(api, org.admin)
    await api.delete(f"/api/v1/boards/{board['id']}", headers=org.admin.headers)
    denied = await api.patch(
        f"/api/v1/boards/{board['id']}", json={"is_archived": False}, headers=org.member.headers
    )
    assert denied.status_code == 403
    assert (await api.get(f"/api/v1/boards/{board['id']}", headers=org.member.headers)).json()[
        "is_archived"
    ] is True


async def test_unauthenticated_requests_are_401_everywhere(api: AsyncClient) -> None:
    fake = uuid.uuid4()
    calls = [
        api.get("/api/v1/boards"),
        api.post("/api/v1/boards", json={"name": "x"}),
        api.get(f"/api/v1/boards/{fake}"),
        api.patch(f"/api/v1/boards/{fake}", json={}),
        api.delete(f"/api/v1/boards/{fake}"),
        api.post(f"/api/v1/boards/{fake}/columns", json={"name": "x"}),
        api.patch(f"/api/v1/columns/{fake}", json={}),
        api.delete(f"/api/v1/columns/{fake}"),
        api.get(f"/api/v1/boards/{fake}/tasks"),
        api.post(f"/api/v1/boards/{fake}/tasks", json={"title": "x"}),
        api.get(f"/api/v1/tasks/{fake}"),
        api.patch(f"/api/v1/tasks/{fake}", json={}),
        api.delete(f"/api/v1/tasks/{fake}"),
        api.post(f"/api/v1/tasks/{fake}/move", json={"column_id": str(fake), "position": 0}),
    ]
    statuses = [(await c).status_code for c in calls]
    assert statuses == [401] * len(calls)
