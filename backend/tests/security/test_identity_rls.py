"""RLS on organizations and users, and the pre-tenant lookup functions (migration 0002)."""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.db.session import SessionFactory, set_context, tenant_session
from app.repositories.identity import IdentityRepository
from tests.conftest import SeededOrgs


async def scalar(session: AsyncSession, sql: str, **params: object) -> object:
    return (await session.execute(text(sql), params)).scalar_one()


async def test_no_context_sees_no_organizations_or_users(
    app_engine: AsyncEngine, seeded: SeededOrgs
) -> None:
    async with app_engine.connect() as conn:
        assert (await conn.execute(text("SELECT count(*) FROM organizations"))).scalar_one() == 0
        assert (await conn.execute(text("SELECT count(*) FROM users"))).scalar_one() == 0


async def test_org_context_sees_only_its_organization(
    app_session_factory: SessionFactory, seeded: SeededOrgs
) -> None:
    async with tenant_session(app_session_factory, seeded.org_a) as session:
        ids = (await session.execute(text("SELECT id FROM organizations"))).scalars().all()
    assert ids == [seeded.org_a]


async def test_users_are_visible_to_org_members_and_to_themselves_only(
    app_session_factory: SessionFactory, seeded: SeededOrgs
) -> None:
    async with tenant_session(app_session_factory, seeded.org_a) as session:
        visible = set((await session.execute(text("SELECT id FROM users"))).scalars().all())
    assert visible == {seeded.user_1, seeded.user_2}  # org A's members, not org B's admin

    async with tenant_session(app_session_factory, seeded.org_a, seeded.user_3) as session:
        visible = set((await session.execute(text("SELECT id FROM users"))).scalars().all())
    assert visible == {seeded.user_1, seeded.user_2, seeded.user_3}  # members of A, plus self

    async with app_session_factory() as session, session.begin():
        await set_context(session, user_id=seeded.user_3)
        visible = set((await session.execute(text("SELECT id FROM users"))).scalars().all())
    assert visible == {seeded.user_3}


async def test_one_user_cannot_modify_or_delete_a_colleague(
    app_session_factory: SessionFactory, admin_engine: AsyncEngine, seeded: SeededOrgs
) -> None:
    async with tenant_session(app_session_factory, seeded.org_a, seeded.user_1) as session:
        updated = await session.execute(
            text("UPDATE users SET full_name = 'pwned' WHERE id = :id"), {"id": seeded.user_2}
        )
        deleted = await session.execute(
            text("DELETE FROM users WHERE id = :id"), {"id": seeded.user_2}
        )
    assert updated.rowcount == 0  # type: ignore[attr-defined]
    assert deleted.rowcount == 0  # type: ignore[attr-defined]
    async with admin_engine.connect() as conn:
        name = (
            await conn.execute(
                text("SELECT full_name FROM users WHERE id = :id"), {"id": seeded.user_2}
            )
        ).scalar_one()
    assert name == "u2"


async def test_a_user_row_can_only_be_inserted_for_the_current_user(
    app_session_factory: SessionFactory,
) -> None:
    insert = text(
        "INSERT INTO users (id, email, password_hash, full_name) VALUES (:id, :e, 'x', 'n')"
    )
    me = uuid.uuid4()
    with pytest.raises(DBAPIError, match="row-level security"):
        async with app_session_factory() as session, session.begin():
            await set_context(session, user_id=me)
            await session.execute(insert, {"id": uuid.uuid4(), "e": f"{uuid.uuid4().hex}@x.com"})
    with pytest.raises(DBAPIError, match="row-level security"):
        async with app_session_factory() as session, session.begin():  # no user context at all
            await session.execute(insert, {"id": me, "e": f"{uuid.uuid4().hex}@x.com"})


async def test_an_organization_row_can_only_be_inserted_for_the_current_org(
    app_session_factory: SessionFactory,
) -> None:
    insert = text("INSERT INTO organizations (id, name, slug) VALUES (:id, 'n', :slug)")
    with pytest.raises(DBAPIError, match="row-level security"):
        async with app_session_factory() as session, session.begin():
            await set_context(session, org_id=uuid.uuid4())
            await session.execute(insert, {"id": uuid.uuid4(), "slug": uuid.uuid4().hex})


async def test_direct_user_reads_stay_blocked_and_unknown_email_finds_nothing(
    app_session_factory: SessionFactory, seeded: SeededOrgs
) -> None:
    async with app_session_factory() as session, session.begin():
        email = (
            await session.execute(
                text("SELECT email FROM users WHERE id = :id"), {"id": seeded.user_1}
            )
        ).scalar_one_or_none()
        assert email is None  # direct reads stay blocked...

        repo = IdentityRepository(session)
        row = (
            await session.execute(
                text("SELECT email FROM auth_find_user_by_email(:e)"), {"e": "ANYONE@example.com"}
            )
        ).first()
        assert row is None
        assert await repo.find_user_by_email("nobody@example.com") is None


async def test_find_user_by_email_returns_the_account(
    app_session_factory: SessionFactory, admin_engine: AsyncEngine, seeded: SeededOrgs
) -> None:
    async with admin_engine.connect() as conn:
        email = (
            await conn.execute(
                text("SELECT email FROM users WHERE id = :id"), {"id": seeded.user_1}
            )
        ).scalar_one()
    async with app_session_factory() as session, session.begin():
        found = await IdentityRepository(session).find_user_by_email(email.upper().lower())
    assert found is not None
    assert found.id == seeded.user_1
    assert found.is_active is True


async def test_list_memberships_returns_only_the_context_users_memberships(
    app_session_factory: SessionFactory, admin_engine: AsyncEngine, seeded: SeededOrgs
) -> None:
    async with admin_engine.begin() as conn:  # user 1 also belongs to org B
        await conn.execute(
            text(
                "INSERT INTO memberships (organization_id, user_id, role) VALUES (:o, :u, 'member')"
            ),
            {"o": seeded.org_b, "u": seeded.user_1},
        )
    async with app_session_factory() as session, session.begin():
        assert await IdentityRepository(session).list_memberships() == []  # no user context

    async with app_session_factory() as session, session.begin():
        await set_context(session, user_id=seeded.user_1)
        rows = await IdentityRepository(session).list_memberships()
    assert {(r.organization_id, r.role) for r in rows} == {
        (seeded.org_a, "admin"),
        (seeded.org_b, "member"),
    }
    assert all(r.organization_name for r in rows)

    async with app_session_factory() as session, session.begin():
        await set_context(session, user_id=seeded.user_2)
        rows = await IdentityRepository(session).list_memberships()
    assert [r.organization_id for r in rows] == [seeded.org_a]


async def test_the_lookup_functions_are_not_callable_by_public(
    app_engine: AsyncEngine,
) -> None:
    async with app_engine.connect() as conn:
        for fn in ("auth_find_user_by_email(text)", "auth_list_memberships()"):
            allowed = (
                await conn.execute(
                    text("SELECT has_function_privilege('public', :fn, 'EXECUTE')"), {"fn": fn}
                )
            ).scalar_one()
            assert allowed is False


@pytest.mark.parametrize("table", ["organizations", "users", "memberships"])
async def test_runtime_role_is_subject_to_forced_rls_on_every_identity_table(
    app_engine: AsyncEngine, table: str
) -> None:
    async with app_engine.connect() as conn:
        flags = (
            await conn.execute(
                text(
                    "SELECT relrowsecurity, relforcerowsecurity, "
                    "pg_get_userbyid(relowner) <> current_user AS not_owner "
                    "FROM pg_class WHERE relname = :t"
                ),
                {"t": table},
            )
        ).one()
    assert tuple(flags) == (True, True, True)
