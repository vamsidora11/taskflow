"""Row-level security on boards, board_columns and tasks (migration 0004)."""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.session import SessionFactory, tenant_session
from tests.conftest import SeededOrgs

TABLES = ["boards", "board_columns", "tasks"]


@pytest.fixture
async def rows(admin_engine: AsyncEngine, seeded: SeededOrgs) -> dict[str, dict[str, uuid.UUID]]:
    """One board, column and task per organization, inserted as superuser (bypasses RLS)."""
    ids: dict[str, dict[str, uuid.UUID]] = {}
    async with admin_engine.begin() as conn:
        for key, org in (("a", seeded.org_a), ("b", seeded.org_b)):
            board, column, task = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
            ids[key] = {"board": board, "column": column, "task": task}
            await conn.execute(
                text("INSERT INTO boards (id, organization_id, name) VALUES (:i, :o, 'B')"),
                {"i": board, "o": org},
            )
            await conn.execute(
                text(
                    "INSERT INTO board_columns (id, organization_id, board_id, name, position) "
                    "VALUES (:i, :o, :b, 'C', 0)"
                ),
                {"i": column, "o": org, "b": board},
            )
            await conn.execute(
                text(
                    "INSERT INTO tasks (id, organization_id, board_id, column_id, title, "
                    "status_position) VALUES (:i, :o, :b, :c, 'T', 0)"
                ),
                {"i": task, "o": org, "b": board, "c": column},
            )
    return ids


@pytest.mark.parametrize("table", TABLES)
async def test_no_context_sees_nothing(
    app_engine: AsyncEngine, rows: dict[str, dict[str, uuid.UUID]], table: str
) -> None:
    async with app_engine.connect() as conn:
        assert (await conn.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one() == 0


@pytest.mark.parametrize("table", TABLES)
async def test_an_org_sees_only_its_own_rows(
    app_session_factory: SessionFactory,
    seeded: SeededOrgs,
    rows: dict[str, dict[str, uuid.UUID]],
    table: str,
) -> None:
    async with tenant_session(app_session_factory, seeded.org_a) as session:
        found = (await session.execute(text(f"SELECT id FROM {table}"))).scalars().all()
    key = {"boards": "board", "board_columns": "column", "tasks": "task"}[table]
    assert found == [rows["a"][key]]


@pytest.mark.parametrize("table", TABLES)
async def test_forced_rls_and_not_owned_by_the_runtime_role(
    app_engine: AsyncEngine, table: str
) -> None:
    async with app_engine.connect() as conn:
        flags = (
            await conn.execute(
                text(
                    "SELECT relrowsecurity, relforcerowsecurity, "
                    "pg_get_userbyid(relowner) <> current_user "
                    "FROM pg_class WHERE relname = :t"
                ),
                {"t": table},
            )
        ).one()
    assert tuple(flags) == (True, True, True)


async def test_rows_cannot_be_created_for_another_org(
    app_session_factory: SessionFactory, seeded: SeededOrgs, rows: dict[str, dict[str, uuid.UUID]]
) -> None:
    statements = [
        ("INSERT INTO boards (organization_id, name) VALUES (:other, 'x')", {}),
        (
            "INSERT INTO board_columns (organization_id, board_id, name, position) "
            "VALUES (:other, :board_b, 'x', 5)",
            {"board_b": rows["b"]["board"]},
        ),
        (
            "INSERT INTO tasks (organization_id, board_id, column_id, title, status_position) "
            "VALUES (:other, :board_b, :col_b, 'x', 9)",
            {"board_b": rows["b"]["board"], "col_b": rows["b"]["column"]},
        ),
    ]
    for sql, params in statements:
        with pytest.raises(DBAPIError, match="row-level security"):
            async with tenant_session(app_session_factory, seeded.org_a) as session:
                await session.execute(text(sql), {"other": seeded.org_b, **params})


async def test_another_orgs_rows_cannot_be_updated_or_deleted(
    app_session_factory: SessionFactory,
    admin_engine: AsyncEngine,
    seeded: SeededOrgs,
    rows: dict[str, dict[str, uuid.UUID]],
) -> None:
    async with tenant_session(app_session_factory, seeded.org_a) as session:
        for table, key, column in (
            ("boards", "board", "name"),
            ("board_columns", "column", "name"),
            ("tasks", "task", "title"),
        ):
            target = {"i": rows["b"][key]}
            upd = await session.execute(
                text(f"UPDATE {table} SET {column} = 'pwned' WHERE id = :i"), target
            )
            dele = await session.execute(text(f"DELETE FROM {table} WHERE id = :i"), target)
            assert (upd.rowcount, dele.rowcount) == (0, 0), table  # type: ignore[attr-defined]
    async with admin_engine.connect() as conn:
        title = (
            await conn.execute(
                text("SELECT title FROM tasks WHERE id = :i"), {"i": rows["b"]["task"]}
            )
        ).scalar_one()
    assert title == "T"


async def test_constraints_reject_bad_data_even_for_a_superuser(
    admin_engine: AsyncEngine, seeded: SeededOrgs, rows: dict[str, dict[str, uuid.UUID]]
) -> None:
    bad = [
        "UPDATE tasks SET priority = 'critical' WHERE id = :t",
        "UPDATE tasks SET status_position = -1 WHERE id = :t",
        "UPDATE board_columns SET position = -1 WHERE id = :c",
    ]
    for sql in bad:
        with pytest.raises(DBAPIError):
            async with admin_engine.begin() as conn:
                await conn.execute(text(sql), {"t": rows["a"]["task"], "c": rows["a"]["column"]})


async def test_column_positions_are_unique_per_board_but_only_checked_at_commit(
    admin_engine: AsyncEngine, seeded: SeededOrgs, rows: dict[str, dict[str, uuid.UUID]]
) -> None:
    insert = text(
        "INSERT INTO board_columns (organization_id, board_id, name, position) "
        "VALUES (:o, :b, :n, :p)"
    )
    params = {"o": seeded.org_a, "b": rows["a"]["board"]}
    with pytest.raises(DBAPIError, match="uq_board_columns_board_id_position"):
        async with admin_engine.begin() as conn:  # a duplicate that survives to commit fails
            await conn.execute(insert, {**params, "n": "dup", "p": 0})
    async with admin_engine.begin() as conn:  # a swap is fine: duplicates are deferred
        await conn.execute(insert, {**params, "n": "second", "p": 1})
        await conn.execute(
            text("UPDATE board_columns SET position = 1 WHERE id = :c"), {"c": rows["a"]["column"]}
        )
        await conn.execute(text("UPDATE board_columns SET position = 0 WHERE name = 'second'"))
