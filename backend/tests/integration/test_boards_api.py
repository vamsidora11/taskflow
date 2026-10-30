import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.helpers import OrgSetup, create_org, make_board, make_task


@pytest.fixture
async def org(api: AsyncClient, admin_engine: AsyncEngine) -> OrgSetup:
    return await create_org(api, admin_engine)


def names(board: dict[str, Any]) -> list[str]:
    return [c["name"] for c in board["columns"]]


# --- creating and reading ---------------------------------------------------------------------


async def test_a_board_gets_the_default_columns(api: AsyncClient, org: OrgSetup) -> None:
    board = await make_board(api, org.manager, "Sprint 1")
    assert names(board) == ["To Do", "In Progress", "Done"]
    assert [c["position"] for c in board["columns"]] == [0, 1, 2]
    assert board["is_archived"] is False
    assert board["created_by"] == org.manager.user_id
    assert {c["board_id"] for c in board["columns"]} == {board["id"]}


async def test_custom_columns_and_no_columns_are_allowed(api: AsyncClient, org: OrgSetup) -> None:
    custom = await make_board(api, org.admin, columns=["Backlog", "Doing", "Review", "Shipped"])
    assert names(custom) == ["Backlog", "Doing", "Review", "Shipped"]
    empty = await make_board(api, org.admin, columns=[])
    assert empty["columns"] == []


async def test_get_board_returns_columns_in_order(api: AsyncClient, org: OrgSetup) -> None:
    board = await make_board(api, org.admin, columns=["A", "B", "C"])
    resp = await api.get(f"/api/v1/boards/{board['id']}", headers=org.member.headers)
    assert resp.status_code == 200
    assert names(resp.json()) == ["A", "B", "C"]


@pytest.mark.parametrize(
    "payload", [{}, {"name": ""}, {"name": "x" * 201}, {"name": "ok", "columns": [""]}]
)
async def test_invalid_boards_are_rejected(
    api: AsyncClient, org: OrgSetup, payload: dict[str, object]
) -> None:
    resp = await api.post("/api/v1/boards", json=payload, headers=org.admin.headers)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_unknown_board_is_404(api: AsyncClient, org: OrgSetup) -> None:
    resp = await api.get(f"/api/v1/boards/{uuid.uuid4()}", headers=org.admin.headers)
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "BOARD_NOT_FOUND"


# --- listing ---------------------------------------------------------------------------------


async def test_boards_paginate_oldest_first(api: AsyncClient, org: OrgSetup) -> None:
    created = [(await make_board(api, org.admin, f"Board {i}"))["id"] for i in range(5)]
    seen: list[str] = []
    cursor: str | None = None
    pages = 0
    while True:
        params: dict[str, str | int] = {"limit": 2}
        if cursor:
            params["cursor"] = cursor
        body = (await api.get("/api/v1/boards", params=params, headers=org.member.headers)).json()
        seen += [b["id"] for b in body["items"]]
        pages += 1
        cursor = body["next_cursor"]
        if cursor is None:
            break
    assert seen == created
    assert pages == 3


async def test_archived_boards_are_hidden_unless_requested(api: AsyncClient, org: OrgSetup) -> None:
    keep = await make_board(api, org.admin, "Keep")
    gone = await make_board(api, org.admin, "Gone")
    assert (
        await api.delete(f"/api/v1/boards/{gone['id']}", headers=org.manager.headers)
    ).status_code == 204

    default = (await api.get("/api/v1/boards", headers=org.member.headers)).json()["items"]
    assert [b["id"] for b in default] == [keep["id"]]
    everything = (
        await api.get(
            "/api/v1/boards", params={"include_archived": True}, headers=org.member.headers
        )
    ).json()["items"]
    assert {b["id"] for b in everything} == {keep["id"], gone["id"]}
    # An archived board is still readable by id.
    assert (
        await api.get(f"/api/v1/boards/{gone['id']}", headers=org.member.headers)
    ).status_code == 200


# --- updating and archiving ---


async def test_update_board_is_partial_and_null_clears_the_description(
    api: AsyncClient, org: OrgSetup
) -> None:
    board = await make_board(api, org.admin, "Old")
    url = f"/api/v1/boards/{board['id']}"
    r1 = await api.patch(url, json={"description": "About"}, headers=org.manager.headers)
    assert (r1.json()["name"], r1.json()["description"]) == ("Old", "About")
    r2 = await api.patch(url, json={"name": "New"}, headers=org.manager.headers)
    assert (r2.json()["name"], r2.json()["description"]) == ("New", "About")
    r3 = await api.patch(url, json={"description": None}, headers=org.manager.headers)
    assert r3.json()["description"] is None
    assert r3.json()["name"] == "New"


async def test_archiving_twice_succeeds_and_restoring_works(
    api: AsyncClient, org: OrgSetup
) -> None:
    board = await make_board(api, org.admin)
    url = f"/api/v1/boards/{board['id']}"
    assert (await api.delete(url, headers=org.admin.headers)).status_code == 204
    assert (await api.delete(url, headers=org.admin.headers)).status_code == 204
    assert (await api.get(url, headers=org.admin.headers)).json()["is_archived"] is True
    restored = await api.patch(url, json={"is_archived": False}, headers=org.manager.headers)
    assert restored.json()["is_archived"] is False
    assert [
        b["id"]
        for b in (await api.get("/api/v1/boards", headers=org.member.headers)).json()["items"]
    ] == [board["id"]]


async def test_an_archived_board_rejects_column_and_task_changes(
    api: AsyncClient, org: OrgSetup
) -> None:
    board = await make_board(api, org.admin)
    task = await make_task(api, org.admin, board["id"])
    await api.delete(f"/api/v1/boards/{board['id']}", headers=org.admin.headers)
    column_id = board["columns"][0]["id"]

    attempts = [
        await api.post(
            f"/api/v1/boards/{board['id']}/columns", json={"name": "X"}, headers=org.admin.headers
        ),
        await api.patch(
            f"/api/v1/columns/{column_id}", json={"name": "X"}, headers=org.admin.headers
        ),
        await api.delete(f"/api/v1/columns/{board['columns'][2]['id']}", headers=org.admin.headers),
        await api.post(
            f"/api/v1/boards/{board['id']}/tasks", json={"title": "T"}, headers=org.admin.headers
        ),
        await api.patch(
            f"/api/v1/tasks/{task['id']}", json={"title": "T2"}, headers=org.admin.headers
        ),
        await api.post(
            f"/api/v1/tasks/{task['id']}/move",
            json={"column_id": column_id, "position": 0},
            headers=org.admin.headers,
        ),
        await api.delete(f"/api/v1/tasks/{task['id']}", headers=org.admin.headers),
    ]
    assert [r.status_code for r in attempts] == [409] * 7
    assert {r.json()["error"]["code"] for r in attempts} == {"BOARD_ARCHIVED"}
    # ...but reads still work and nothing changed.
    assert (await api.get(f"/api/v1/tasks/{task['id']}", headers=org.member.headers)).json()[
        "title"
    ] == "A task"


# --- columns ---


async def column_names(api: AsyncClient, org: OrgSetup, board_id: str) -> list[tuple[str, int]]:
    board = (await api.get(f"/api/v1/boards/{board_id}", headers=org.admin.headers)).json()
    return [(c["name"], c["position"]) for c in board["columns"]]


async def test_a_column_is_appended_or_inserted_at_a_position(
    api: AsyncClient, org: OrgSetup
) -> None:
    board = await make_board(api, org.admin, columns=["A", "B"])
    url = f"/api/v1/boards/{board['id']}/columns"
    appended = await api.post(url, json={"name": "C"}, headers=org.manager.headers)
    assert appended.status_code == 201
    assert appended.json()["position"] == 2
    inserted = await api.post(url, json={"name": "Z", "position": 0}, headers=org.manager.headers)
    assert inserted.json()["position"] == 0
    assert await column_names(api, org, board["id"]) == [("Z", 0), ("A", 1), ("B", 2), ("C", 3)]
    far = await api.post(url, json={"name": "End", "position": 99}, headers=org.manager.headers)
    assert far.json()["position"] == 4


async def test_columns_can_be_renamed_and_reordered(api: AsyncClient, org: OrgSetup) -> None:
    board = await make_board(api, org.admin, columns=["A", "B", "C", "D"])
    d = board["columns"][3]["id"]
    moved = await api.patch(
        f"/api/v1/columns/{d}", json={"position": 1, "name": "D2"}, headers=org.manager.headers
    )
    assert moved.status_code == 200
    assert (moved.json()["name"], moved.json()["position"]) == ("D2", 1)
    assert await column_names(api, org, board["id"]) == [("A", 0), ("D2", 1), ("B", 2), ("C", 3)]
    a = board["columns"][0]["id"]
    await api.patch(f"/api/v1/columns/{a}", json={"position": 3}, headers=org.manager.headers)
    assert await column_names(api, org, board["id"]) == [("D2", 0), ("B", 1), ("C", 2), ("A", 3)]


async def test_deleting_a_column_closes_the_gap(api: AsyncClient, org: OrgSetup) -> None:
    board = await make_board(api, org.admin, columns=["A", "B", "C"])
    resp = await api.delete(
        f"/api/v1/columns/{board['columns'][1]['id']}", headers=org.manager.headers
    )
    assert resp.status_code == 204
    assert await column_names(api, org, board["id"]) == [("A", 0), ("C", 1)]


async def test_a_column_with_tasks_cannot_be_deleted_until_it_is_emptied(
    api: AsyncClient, org: OrgSetup
) -> None:
    board = await make_board(api, org.admin)
    todo = board["columns"][0]["id"]
    task = await make_task(api, org.admin, board["id"])
    blocked = await api.delete(f"/api/v1/columns/{todo}", headers=org.admin.headers)
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "COLUMN_NOT_EMPTY"

    await api.delete(f"/api/v1/tasks/{task['id']}", headers=org.admin.headers)  # soft delete
    assert (
        await api.delete(f"/api/v1/columns/{todo}", headers=org.admin.headers)
    ).status_code == 204


async def test_unknown_columns_are_404(api: AsyncClient, org: OrgSetup) -> None:
    for method in ("PATCH", "DELETE"):
        resp = await api.request(
            method,
            f"/api/v1/columns/{uuid.uuid4()}",
            json={"name": "x"} if method == "PATCH" else None,
            headers=org.admin.headers,
        )
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "COLUMN_NOT_FOUND"
    resp = await api.post(
        f"/api/v1/boards/{uuid.uuid4()}/columns", json={"name": "x"}, headers=org.admin.headers
    )
    assert resp.status_code == 404


async def test_column_positions_stay_dense_under_concurrent_inserts(
    api: AsyncClient, org: OrgSetup
) -> None:
    import asyncio

    board = await make_board(api, org.admin, columns=["Start"])
    url = f"/api/v1/boards/{board['id']}/columns"
    results = await asyncio.gather(
        *[api.post(url, json={"name": f"C{i}"}, headers=org.admin.headers) for i in range(6)]
    )
    assert [r.status_code for r in results] == [201] * 6
    positions = sorted(p for _, p in await column_names(api, org, board["id"]))
    assert positions == list(range(7))
