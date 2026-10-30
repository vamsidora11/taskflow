import asyncio
import uuid
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.repositories.task import TaskRepository
from tests.helpers import (
    OrgSetup,
    assert_positions_dense,
    create_org,
    list_all_tasks,
    make_board,
    make_task,
)


@pytest.fixture
async def org(api: AsyncClient, admin_engine: AsyncEngine) -> OrgSetup:
    return await create_org(api, admin_engine)


@pytest.fixture
async def board(api: AsyncClient, org: OrgSetup) -> dict[str, Any]:
    return await make_board(api, org.admin, "Work")


def col(board: dict[str, Any], index: int) -> str:
    return str(board["columns"][index]["id"])


async def titles(api: AsyncClient, org: OrgSetup, board: dict[str, Any], column: str) -> list[str]:
    tasks = await list_all_tasks(api, org.admin, board["id"], column_id=column)
    return [t["title"] for t in sorted(tasks, key=lambda t: t["position"])]


# --- creating -------------------------------------------------------------------------------


async def test_a_task_lands_at_the_bottom_of_the_first_column(
    api: AsyncClient, org: OrgSetup, board: dict[str, Any]
) -> None:
    first = await make_task(api, org.member, board["id"], "One")
    second = await make_task(api, org.member, board["id"], "Two")
    assert first["column_id"] == second["column_id"] == col(board, 0)
    assert (first["position"], second["position"]) == (0, 1)
    assert first["priority"] == "medium"
    assert first["created_by"] == org.member.user_id
    assert first["assignee_id"] is None


async def test_a_task_can_target_a_column_and_carries_all_fields(
    api: AsyncClient, org: OrgSetup, board: dict[str, Any]
) -> None:
    task = await make_task(
        api,
        org.manager,
        board["id"],
        "Deck",
        description="Include revenue",
        priority="urgent",
        assignee_id=org.member.user_id,
        due_date="2026-11-15",
        column_id=col(board, 2),
    )
    assert task["column_id"] == col(board, 2)
    assert (task["priority"], task["due_date"]) == ("urgent", "2026-11-15")
    assert task["assignee_id"] == org.member.user_id
    again = await api.get(f"/api/v1/tasks/{task['id']}", headers=org.member.headers)
    assert again.json() == task


async def test_creating_in_another_boards_or_unknown_column_is_404(
    api: AsyncClient, org: OrgSetup, board: dict[str, Any]
) -> None:
    other = await make_board(api, org.admin, "Other")
    for column_id in (col(other, 0), str(uuid.uuid4())):
        resp = await api.post(
            f"/api/v1/boards/{board['id']}/tasks",
            json={"title": "x", "column_id": column_id},
            headers=org.admin.headers,
        )
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "COLUMN_NOT_FOUND"


async def test_creating_on_an_unknown_board_or_a_board_without_columns(
    api: AsyncClient, org: OrgSetup
) -> None:
    missing = await api.post(
        f"/api/v1/boards/{uuid.uuid4()}/tasks", json={"title": "x"}, headers=org.admin.headers
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "BOARD_NOT_FOUND"
    bare = await make_board(api, org.admin, columns=[])
    resp = await api.post(
        f"/api/v1/boards/{bare['id']}/tasks", json={"title": "x"}, headers=org.admin.headers
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "BOARD_HAS_NO_COLUMNS"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"title": ""},
        {"title": "x" * 201},
        {"title": "ok", "priority": "critical"},
        {"title": "ok", "due_date": "tomorrow"},
        {"title": "ok", "description": "x" * 5001},
    ],
)
async def test_invalid_tasks_are_rejected(
    api: AsyncClient, org: OrgSetup, board: dict[str, Any], payload: dict[str, object]
) -> None:
    resp = await api.post(
        f"/api/v1/boards/{board['id']}/tasks", json=payload, headers=org.admin.headers
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_the_assignee_must_belong_to_the_organization(
    api: AsyncClient, admin_engine: AsyncEngine, org: OrgSetup, board: dict[str, Any]
) -> None:
    stranger = await create_org(api, admin_engine)
    for assignee in (stranger.admin.user_id, str(uuid.uuid4())):
        resp = await api.post(
            f"/api/v1/boards/{board['id']}/tasks",
            json={"title": "x", "assignee_id": assignee},
            headers=org.admin.headers,
        )
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "INVALID_ASSIGNEE"


# --- ownership rules --------------------------------------------------------------------------


async def test_a_member_creates_tasks_only_for_themselves_or_unassigned(
    api: AsyncClient, org: OrgSetup, board: dict[str, Any]
) -> None:
    mine = await make_task(api, org.member, board["id"], "Mine", assignee_id=org.member.user_id)
    assert mine["assignee_id"] == org.member.user_id
    for other in (org.manager.user_id, org.admin.user_id):
        resp = await api.post(
            f"/api/v1/boards/{board['id']}/tasks",
            json={"title": "x", "assignee_id": other},
            headers=org.member.headers,
        )
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "PERMISSION_DENIED"


async def test_a_member_edits_only_tasks_assigned_to_them(
    api: AsyncClient, org: OrgSetup, board: dict[str, Any]
) -> None:
    mine = await make_task(api, org.manager, board["id"], "Mine", assignee_id=org.member.user_id)
    theirs = await make_task(
        api, org.manager, board["id"], "Theirs", assignee_id=org.manager.user_id
    )
    loose = await make_task(api, org.manager, board["id"], "Loose")

    ok = await api.patch(
        f"/api/v1/tasks/{mine['id']}",
        json={"title": "Mine!", "priority": "high"},
        headers=org.member.headers,
    )
    assert ok.status_code == 200
    assert (ok.json()["title"], ok.json()["priority"]) == ("Mine!", "high")
    for task in (theirs, loose):
        denied = await api.patch(
            f"/api/v1/tasks/{task['id']}", json={"title": "hijack"}, headers=org.member.headers
        )
        assert denied.status_code == 403
        assert (await api.get(f"/api/v1/tasks/{task['id']}", headers=org.admin.headers)).json()[
            "title"
        ] == task["title"]


async def test_a_member_cannot_reassign_even_their_own_task(
    api: AsyncClient, org: OrgSetup, board: dict[str, Any]
) -> None:
    mine = await make_task(api, org.manager, board["id"], assignee_id=org.member.user_id)
    url = f"/api/v1/tasks/{mine['id']}"
    for body in ({"assignee_id": org.manager.user_id}, {"assignee_id": None}):
        denied = await api.patch(url, json=body, headers=org.member.headers)
        assert denied.status_code == 403
    same = await api.patch(
        url, json={"assignee_id": org.member.user_id}, headers=org.member.headers
    )
    assert same.status_code == 200  # re-stating the current assignee is not a reassignment
    assert (await api.get(url, headers=org.admin.headers)).json()[
        "assignee_id"
    ] == org.member.user_id


async def test_managers_and_admins_edit_and_reassign_any_task(
    api: AsyncClient, org: OrgSetup, board: dict[str, Any]
) -> None:
    task = await make_task(api, org.member, board["id"], assignee_id=org.member.user_id)
    url = f"/api/v1/tasks/{task['id']}"
    by_manager = await api.patch(
        url, json={"assignee_id": org.admin.user_id}, headers=org.manager.headers
    )
    assert by_manager.json()["assignee_id"] == org.admin.user_id
    by_admin = await api.patch(
        url, json={"assignee_id": None, "title": "Reset"}, headers=org.admin.headers
    )
    assert (by_admin.json()["assignee_id"], by_admin.json()["title"]) == (None, "Reset")


async def test_only_managers_and_admins_delete_tasks(
    api: AsyncClient, org: OrgSetup, board: dict[str, Any]
) -> None:
    mine = await make_task(api, org.manager, board["id"], assignee_id=org.member.user_id)
    denied = await api.delete(f"/api/v1/tasks/{mine['id']}", headers=org.member.headers)
    assert denied.status_code == 403  # even for a task assigned to the member
    assert (
        await api.delete(f"/api/v1/tasks/{mine['id']}", headers=org.manager.headers)
    ).status_code == 204


async def test_a_member_moves_only_their_own_tasks(
    api: AsyncClient, org: OrgSetup, board: dict[str, Any]
) -> None:
    mine = await make_task(api, org.manager, board["id"], "Mine", assignee_id=org.member.user_id)
    theirs = await make_task(api, org.manager, board["id"], "Theirs")
    target = {"column_id": col(board, 1), "position": 0}
    ok = await api.post(f"/api/v1/tasks/{mine['id']}/move", json=target, headers=org.member.headers)
    assert ok.status_code == 200
    denied = await api.post(
        f"/api/v1/tasks/{theirs['id']}/move", json=target, headers=org.member.headers
    )
    assert denied.status_code == 403
    assert (await api.get(f"/api/v1/tasks/{theirs['id']}", headers=org.admin.headers)).json()[
        "column_id"
    ] == col(board, 0)


# --- updating ------------------------------------------------------------------------------------


async def test_update_is_partial_and_null_clears_optional_fields(
    api: AsyncClient, org: OrgSetup, board: dict[str, Any]
) -> None:
    task = await make_task(api, org.admin, board["id"], "T", description="D", due_date="2026-12-01")
    url = f"/api/v1/tasks/{task['id']}"
    r1 = await api.patch(url, json={"title": "T2"}, headers=org.admin.headers)
    assert (r1.json()["title"], r1.json()["description"], r1.json()["due_date"]) == (
        "T2",
        "D",
        "2026-12-01",
    )
    r2 = await api.patch(
        url, json={"description": None, "due_date": None}, headers=org.admin.headers
    )
    assert (r2.json()["title"], r2.json()["description"], r2.json()["due_date"]) == (
        "T2",
        None,
        None,
    )
    assert r2.json()["updated_at"] >= task["updated_at"]


@pytest.mark.parametrize(
    "body", [{"title": None}, {"priority": None}, {"title": ""}, {"priority": "x"}]
)
async def test_required_fields_cannot_be_blanked(
    api: AsyncClient, org: OrgSetup, board: dict[str, Any], body: dict[str, object]
) -> None:
    task = await make_task(api, org.admin, board["id"])
    resp = await api.patch(f"/api/v1/tasks/{task['id']}", json=body, headers=org.admin.headers)
    assert resp.status_code == 422


async def test_update_cannot_change_the_column(
    api: AsyncClient, org: OrgSetup, board: dict[str, Any]
) -> None:
    task = await make_task(api, org.admin, board["id"])
    resp = await api.patch(
        f"/api/v1/tasks/{task['id']}",
        json={"column_id": col(board, 2), "title": "t"},
        headers=org.admin.headers,
    )
    assert resp.status_code == 200
    assert resp.json()["column_id"] == col(board, 0)


# --- deleting ----------------------------------------------------------------------------------


async def test_delete_is_soft_hides_the_task_and_closes_the_gap(
    api: AsyncClient, admin_engine: AsyncEngine, org: OrgSetup, board: dict[str, Any]
) -> None:
    a, b, c = [await make_task(api, org.admin, board["id"], n) for n in "ABC"]
    assert (
        await api.delete(f"/api/v1/tasks/{b['id']}", headers=org.manager.headers)
    ).status_code == 204

    assert (await api.get(f"/api/v1/tasks/{b['id']}", headers=org.admin.headers)).status_code == 404
    again = await api.delete(f"/api/v1/tasks/{b['id']}", headers=org.admin.headers)
    assert again.status_code == 404
    listed = await list_all_tasks(api, org.admin, board["id"])
    assert [(t["title"], t["position"]) for t in listed] == [("A", 0), ("C", 1)]
    await assert_positions_dense(api, org.admin, board)
    async with admin_engine.connect() as conn:  # the row is still there, flagged
        deleted_at = (
            await conn.execute(text("SELECT deleted_at FROM tasks WHERE id = :i"), {"i": b["id"]})
        ).scalar_one()
    assert deleted_at is not None
    assert (a["position"], c["position"]) == (0, 2)  # c was at 2 before the gap closed


async def test_a_deleted_task_cannot_be_edited_or_moved(
    api: AsyncClient, org: OrgSetup, board: dict[str, Any]
) -> None:
    task = await make_task(api, org.admin, board["id"])
    await api.delete(f"/api/v1/tasks/{task['id']}", headers=org.admin.headers)
    patch = await api.patch(
        f"/api/v1/tasks/{task['id']}", json={"title": "z"}, headers=org.admin.headers
    )
    move = await api.post(
        f"/api/v1/tasks/{task['id']}/move",
        json={"column_id": col(board, 1), "position": 0},
        headers=org.admin.headers,
    )
    assert (patch.status_code, move.status_code) == (404, 404)
    assert patch.json()["error"]["code"] == "TASK_NOT_FOUND"


# --- listing and filters -------------------------------------------------------------------------


@pytest.fixture
async def busy_board(api: AsyncClient, org: OrgSetup, board: dict[str, Any]) -> dict[str, Any]:
    """Seven tasks spread over columns, assignees and priorities."""
    spec = [
        ("t1", 0, "low", None),
        ("t2", 0, "high", "member"),
        ("t3", 0, "high", "manager"),
        ("t4", 1, "high", "member"),
        ("t5", 1, "urgent", "member"),
        ("t6", 2, "high", "member"),
        ("t7", 2, "low", "manager"),
    ]
    who = {"member": org.member.user_id, "manager": org.manager.user_id, None: None}
    for title, column, priority, assignee in spec:
        await make_task(
            api,
            org.admin,
            board["id"],
            title,
            column_id=col(board, column),
            priority=priority,
            assignee_id=who[assignee],
        )
    return board


async def test_tasks_list_in_board_order(
    api: AsyncClient, org: OrgSetup, busy_board: dict[str, Any]
) -> None:
    tasks = await list_all_tasks(api, org.member, busy_board["id"])
    assert [t["title"] for t in tasks] == ["t1", "t2", "t3", "t4", "t5", "t6", "t7"]


@pytest.mark.parametrize(
    ("filters", "expected"),
    [
        ({"priority": "high"}, ["t2", "t3", "t4", "t6"]),
        ({"column_id": 0}, ["t1", "t2", "t3"]),
        ({"assignee": "member"}, ["t2", "t4", "t5", "t6"]),
        ({"column_id": 0, "priority": "high"}, ["t2", "t3"]),
        ({"column_id": 1, "assignee": "member"}, ["t4", "t5"]),
        ({"assignee": "member", "priority": "high"}, ["t2", "t4", "t6"]),
        ({"column_id": 2, "assignee": "member", "priority": "high"}, ["t6"]),
        ({"column_id": 2, "assignee": "member", "priority": "urgent"}, []),
        ({"priority": "low", "assignee": "manager"}, ["t7"]),
    ],
)
async def test_filters_combine(
    api: AsyncClient,
    org: OrgSetup,
    busy_board: dict[str, Any],
    filters: dict[str, Any],
    expected: list[str],
) -> None:
    params: dict[str, Any] = {}
    if "column_id" in filters:
        params["column_id"] = col(busy_board, filters["column_id"])
    if "assignee" in filters:
        params["assignee_id"] = {"member": org.member.user_id, "manager": org.manager.user_id}[
            filters["assignee"]
        ]
    if "priority" in filters:
        params["priority"] = filters["priority"]
    tasks = await list_all_tasks(api, org.member, busy_board["id"], **params)
    assert [t["title"] for t in tasks] == expected


async def test_filters_hold_while_paginating(
    api: AsyncClient, org: OrgSetup, busy_board: dict[str, Any]
) -> None:
    seen: list[str] = []
    cursor: str | None = None
    while True:
        params: dict[str, Any] = {"priority": "high", "limit": 3}
        if cursor:
            params["cursor"] = cursor
        body = (
            await api.get(
                f"/api/v1/boards/{busy_board['id']}/tasks",
                params=params,
                headers=org.member.headers,
            )
        ).json()
        assert len(body["items"]) <= 3
        assert {t["priority"] for t in body["items"]} == {"high"}
        seen += [t["title"] for t in body["items"]]
        cursor = body["next_cursor"]
        if cursor is None:
            break
    assert seen == ["t2", "t3", "t4", "t6"]


async def test_pagination_walks_every_task_once_in_order(
    api: AsyncClient, org: OrgSetup, busy_board: dict[str, Any]
) -> None:
    seen: list[str] = []
    cursor: str | None = None
    pages = 0
    while True:
        params: dict[str, Any] = {"limit": 2}
        if cursor:
            params["cursor"] = cursor
        body = (
            await api.get(
                f"/api/v1/boards/{busy_board['id']}/tasks",
                params=params,
                headers=org.member.headers,
            )
        ).json()
        seen += [t["title"] for t in body["items"]]
        pages += 1
        cursor = body["next_cursor"]
        if cursor is None:
            break
    assert seen == ["t1", "t2", "t3", "t4", "t5", "t6", "t7"]
    assert pages == 4


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 101},
        {"priority": "x"},
        {"column_id": "nope"},
        {"assignee_id": "nope"},
    ],
)
async def test_bad_list_params_are_422(
    api: AsyncClient, org: OrgSetup, board: dict[str, Any], params: dict[str, Any]
) -> None:
    resp = await api.get(
        f"/api/v1/boards/{board['id']}/tasks", params=params, headers=org.member.headers
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_a_malformed_cursor_is_422(
    api: AsyncClient, org: OrgSetup, board: dict[str, Any]
) -> None:
    resp = await api.get(
        f"/api/v1/boards/{board['id']}/tasks",
        params={"cursor": "garbage"},
        headers=org.member.headers,
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "INVALID_CURSOR"


async def test_listing_an_unknown_board_is_404(api: AsyncClient, org: OrgSetup) -> None:
    resp = await api.get(f"/api/v1/boards/{uuid.uuid4()}/tasks", headers=org.member.headers)
    assert resp.status_code == 404


# --- moving ----------------------------------------------------------------------------------


@pytest.fixture
async def lanes(
    api: AsyncClient, org: OrgSetup, board: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    """To Do holds A B C D; In Progress holds X Y."""
    tasks: dict[str, dict[str, Any]] = {}
    for name in "ABCD":
        tasks[name] = await make_task(api, org.admin, board["id"], name)
    for name in "XY":
        tasks[name] = await make_task(api, org.admin, board["id"], name, column_id=col(board, 1))
    return tasks


async def move(api: AsyncClient, org: OrgSetup, task_id: str, column: str, position: int) -> Any:
    return await api.post(
        f"/api/v1/tasks/{task_id}/move",
        json={"column_id": column, "position": position},
        headers=org.manager.headers,
    )


@pytest.mark.parametrize(
    ("task", "to", "expected"),
    [
        ("A", 2, ["B", "C", "A", "D"]),  # down
        ("D", 0, ["D", "A", "B", "C"]),  # up to the top
        ("C", 1, ["A", "C", "B", "D"]),  # up one
        ("B", 3, ["A", "C", "D", "B"]),  # to the bottom
        ("B", 99, ["A", "C", "D", "B"]),  # past the end clamps
        ("B", 1, ["A", "B", "C", "D"]),  # same slot is a no-op
    ],
)
async def test_reordering_within_a_column(
    api: AsyncClient,
    org: OrgSetup,
    board: dict[str, Any],
    lanes: dict[str, Any],
    task: str,
    to: int,
    expected: list[str],
) -> None:
    resp = await move(api, org, lanes[task]["id"], col(board, 0), to)
    assert resp.status_code == 200
    assert resp.json()["column_id"] == col(board, 0)
    assert await titles(api, org, board, col(board, 0)) == expected
    await assert_positions_dense(api, org.admin, board)


@pytest.mark.parametrize(
    ("task", "to", "todo", "doing"),
    [
        ("B", 0, ["A", "C", "D"], ["B", "X", "Y"]),
        ("B", 1, ["A", "C", "D"], ["X", "B", "Y"]),
        ("A", 2, ["B", "C", "D"], ["X", "Y", "A"]),
        ("D", 99, ["A", "B", "C"], ["X", "Y", "D"]),
    ],
)
async def test_moving_to_another_column_renumbers_both(
    api: AsyncClient,
    org: OrgSetup,
    board: dict[str, Any],
    lanes: dict[str, Any],
    task: str,
    to: int,
    todo: list[str],
    doing: list[str],
) -> None:
    resp = await move(api, org, lanes[task]["id"], col(board, 1), to)
    assert resp.status_code == 200
    assert resp.json()["column_id"] == col(board, 1)
    assert await titles(api, org, board, col(board, 0)) == todo
    assert await titles(api, org, board, col(board, 1)) == doing
    await assert_positions_dense(api, org.admin, board)


async def test_a_move_into_an_empty_column(
    api: AsyncClient, org: OrgSetup, board: dict[str, Any], lanes: dict[str, Any]
) -> None:
    resp = await move(api, org, lanes["A"]["id"], col(board, 2), 5)
    assert resp.json()["position"] == 0
    await assert_positions_dense(api, org.admin, board)


async def test_a_move_skips_over_soft_deleted_tasks(
    api: AsyncClient, org: OrgSetup, board: dict[str, Any], lanes: dict[str, Any]
) -> None:
    await api.delete(f"/api/v1/tasks/{lanes['B']['id']}", headers=org.admin.headers)
    resp = await move(api, org, lanes["A"]["id"], col(board, 0), 1)
    assert resp.status_code == 200
    assert await titles(api, org, board, col(board, 0)) == ["C", "A", "D"]
    await assert_positions_dense(api, org.admin, board)


async def test_moving_to_a_column_of_another_board_or_unknown_is_404_and_changes_nothing(
    api: AsyncClient, org: OrgSetup, board: dict[str, Any], lanes: dict[str, Any]
) -> None:
    other = await make_board(api, org.admin, "Other")
    for column_id in (col(other, 0), str(uuid.uuid4())):
        resp = await move(api, org, lanes["A"]["id"], column_id, 0)
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "COLUMN_NOT_FOUND"
    assert await titles(api, org, board, col(board, 0)) == ["A", "B", "C", "D"]


@pytest.mark.parametrize(
    "body",
    [
        {"position": 0},
        {"column_id": str(uuid.uuid4()), "position": -1},
        {"column_id": "x", "position": 0},
    ],
)
async def test_invalid_moves_are_422(
    api: AsyncClient, org: OrgSetup, lanes: dict[str, Any], body: dict[str, Any]
) -> None:
    resp = await api.post(
        f"/api/v1/tasks/{lanes['A']['id']}/move", json=body, headers=org.manager.headers
    )
    assert resp.status_code == 422


async def test_a_failed_move_leaves_no_partial_change(
    api: AsyncClient,
    org: OrgSetup,
    board: dict[str, Any],
    lanes: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The move renumbers two columns and then updates the task. If the second renumbering
    blows up, the first must be rolled back too."""
    real = TaskRepository.shift_positions
    calls = 0

    async def flaky(self: TaskRepository, *args: Any, **kwargs: Any) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("simulated crash between the two renumberings")
        await real(self, *args, **kwargs)

    monkeypatch.setattr(TaskRepository, "shift_positions", flaky)
    quiet = AsyncClient(
        transport=ASGITransport(app=api._transport.app, raise_app_exceptions=False),  # type: ignore[attr-defined]
        base_url="https://test",
    )
    async with quiet:
        resp = await quiet.post(
            f"/api/v1/tasks/{lanes['B']['id']}/move",
            json={"column_id": col(board, 1), "position": 0},
            headers=org.manager.headers,
        )
    assert resp.status_code == 500
    assert calls == 2
    monkeypatch.undo()

    assert await titles(api, org, board, col(board, 0)) == ["A", "B", "C", "D"]
    assert await titles(api, org, board, col(board, 1)) == ["X", "Y"]
    await assert_positions_dense(api, org.admin, board)


# --- concurrency ---------------------------------------------------------------------------------


async def test_concurrent_creates_get_distinct_dense_positions(
    api: AsyncClient, org: OrgSetup, board: dict[str, Any]
) -> None:
    results = await asyncio.gather(
        *[
            api.post(
                f"/api/v1/boards/{board['id']}/tasks",
                json={"title": f"T{i}"},
                headers=org.member.headers,
            )
            for i in range(8)
        ]
    )
    assert [r.status_code for r in results] == [201] * 8
    assert sorted(r.json()["position"] for r in results) == list(range(8))
    await assert_positions_dense(api, org.admin, board)


async def test_concurrent_moves_keep_positions_dense(
    api: AsyncClient, org: OrgSetup, board: dict[str, Any], lanes: dict[str, Any]
) -> None:
    jobs = [
        move(api, org, lanes["A"]["id"], col(board, 1), 0),
        move(api, org, lanes["B"]["id"], col(board, 1), 1),
        move(api, org, lanes["C"]["id"], col(board, 2), 0),
        move(api, org, lanes["D"]["id"], col(board, 0), 0),
        move(api, org, lanes["X"]["id"], col(board, 0), 1),
    ]
    results = await asyncio.gather(*jobs)
    assert [r.status_code for r in results] == [200] * 5
    await assert_positions_dense(api, org.admin, board)
    assert len(await list_all_tasks(api, org.admin, board["id"])) == 6
