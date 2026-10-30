"""Proves that PostgreSQL itself, not just application code, isolates tenants (PLAN.md 4)."""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.session import SessionFactory, tenant_session
from tests.conftest import SeededOrgs

COUNT = text("SELECT count(*) FROM memberships")


async def test_app_role_without_org_setting_sees_no_rows(
    app_engine: AsyncEngine, admin_engine: AsyncEngine, seeded: SeededOrgs
) -> None:
    async with admin_engine.connect() as conn:  # sanity: the rows exist
        assert (await conn.execute(COUNT)).scalar_one() >= 3
    async with app_engine.connect() as conn:
        assert (await conn.execute(COUNT)).scalar_one() == 0


async def test_empty_org_setting_sees_no_rows(app_engine: AsyncEngine, seeded: SeededOrgs) -> None:
    async with app_engine.begin() as conn:
        await conn.execute(text("SELECT set_config('app.current_org_id', '', true)"))
        assert (await conn.execute(COUNT)).scalar_one() == 0


@pytest.mark.parametrize(("org_attr", "expected"), [("org_a", 2), ("org_b", 1)])
async def test_org_setting_returns_only_that_orgs_rows(
    app_session_factory: SessionFactory, seeded: SeededOrgs, org_attr: str, expected: int
) -> None:
    org_id = getattr(seeded, org_attr)
    async with tenant_session(app_session_factory, org_id) as session:
        rows = (await session.execute(text("SELECT organization_id FROM memberships"))).all()
    assert len(rows) == expected
    assert {r.organization_id for r in rows} == {org_id}


async def test_cannot_insert_row_for_another_org(
    app_session_factory: SessionFactory, seeded: SeededOrgs
) -> None:
    with pytest.raises(DBAPIError, match="row-level security"):
        async with tenant_session(app_session_factory, seeded.org_a) as session:
            await session.execute(
                text(
                    "INSERT INTO memberships (organization_id, user_id, role) "
                    "VALUES (:org, :user, 'member')"
                ),
                {"org": seeded.org_b, "user": seeded.user_1},
            )


async def test_cannot_update_or_delete_another_orgs_rows(
    app_session_factory: SessionFactory, admin_engine: AsyncEngine, seeded: SeededOrgs
) -> None:
    async with tenant_session(app_session_factory, seeded.org_a) as session:
        updated = await session.execute(
            text("UPDATE memberships SET role = 'member' WHERE id = :id"),
            {"id": seeded.membership_b3},
        )
        deleted = await session.execute(
            text("DELETE FROM memberships WHERE id = :id"), {"id": seeded.membership_b3}
        )
    assert updated.rowcount == 0  # type: ignore[attr-defined]
    assert deleted.rowcount == 0  # type: ignore[attr-defined]
    async with admin_engine.connect() as conn:
        role = (
            await conn.execute(
                text("SELECT role FROM memberships WHERE id = :id"), {"id": seeded.membership_b3}
            )
        ).scalar_one()
    assert role == "admin"


async def test_org_setting_does_not_leak_to_next_transaction(
    app_session_factory: SessionFactory, app_engine: AsyncEngine, seeded: SeededOrgs
) -> None:
    async with tenant_session(app_session_factory, seeded.org_a) as session:
        assert (await session.execute(COUNT)).scalar_one() == 2
    # The engine holds one connection, so this reuses the connection that just served org A.
    async with app_engine.connect() as conn:
        assert (await conn.execute(COUNT)).scalar_one() == 0


async def test_tenant_session_rolls_back_on_error(
    app_session_factory: SessionFactory, admin_engine: AsyncEngine, seeded: SeededOrgs
) -> None:
    with pytest.raises(RuntimeError):
        async with tenant_session(app_session_factory, seeded.org_a) as session:
            await session.execute(
                text("UPDATE memberships SET role = 'manager' WHERE id = :id"),
                {"id": seeded.membership_a1},
            )
            raise RuntimeError("boom")
    async with admin_engine.connect() as conn:
        role = (
            await conn.execute(
                text("SELECT role FROM memberships WHERE id = :id"), {"id": seeded.membership_a1}
            )
        ).scalar_one()
    assert role == "admin"


async def test_app_role_cannot_bypass_rls(app_engine: AsyncEngine, seeded: SeededOrgs) -> None:
    async with app_engine.connect() as conn:
        role = (
            await conn.execute(
                text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
            )
        ).one()
        assert (role.rolsuper, role.rolbypassrls) == (False, False)

        table = (
            await conn.execute(
                text(
                    "SELECT c.relrowsecurity, c.relforcerowsecurity, "
                    "pg_get_userbyid(c.relowner) AS owner, current_user AS me "
                    "FROM pg_class c WHERE c.relname = 'memberships'"
                )
            )
        ).one()
    assert table.relrowsecurity and table.relforcerowsecurity
    assert table.owner != table.me


@pytest.mark.parametrize(
    "ddl",
    [
        "CREATE TABLE should_not_exist (id int)",
        "ALTER TABLE memberships DISABLE ROW LEVEL SECURITY",
        "DROP POLICY tenant_isolation ON memberships",
        "DROP TABLE memberships",
    ],
)
async def test_app_role_cannot_run_ddl(app_engine: AsyncEngine, ddl: str) -> None:
    with pytest.raises(DBAPIError):
        async with app_engine.begin() as conn:
            await conn.execute(text(ddl))


async def test_users_table_rejects_non_lowercase_email(admin_engine: AsyncEngine) -> None:
    with pytest.raises(DBAPIError):
        async with admin_engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO users (email, password_hash, full_name) "
                    "VALUES (:e, 'x', 'Mixed Case')"
                ),
                {"e": f"Mixed-{uuid.uuid4().hex[:6]}@Example.com"},
            )
