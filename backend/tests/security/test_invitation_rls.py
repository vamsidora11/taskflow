"""Row-level security on invitations and the token lookup function (migration 0003)."""

import hashlib
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.session import SessionFactory, set_context, tenant_session
from app.repositories.identity import IdentityRepository
from tests.conftest import SeededOrgs


def digest(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


@pytest.fixture
async def invitations(admin_engine: AsyncEngine, seeded: SeededOrgs) -> dict[str, uuid.UUID]:
    ids = {"a": uuid.uuid4(), "b": uuid.uuid4()}
    async with admin_engine.begin() as conn:
        for key, org in (("a", seeded.org_a), ("b", seeded.org_b)):
            await conn.execute(
                text(
                    "INSERT INTO invitations "
                    "(id, organization_id, email, role, token_hash, expires_at) "
                    "VALUES (:id, :o, :e, 'member', :h, now() + interval '1 day')"
                ),
                {"id": ids[key], "o": org, "e": f"{key}@example.com", "h": digest(f"token-{key}")},
            )
    return ids


async def test_no_context_sees_no_invitations(
    app_engine: AsyncEngine, invitations: dict[str, uuid.UUID]
) -> None:
    async with app_engine.connect() as conn:
        assert (await conn.execute(text("SELECT count(*) FROM invitations"))).scalar_one() == 0


async def test_an_org_sees_only_its_own_invitations(
    app_session_factory: SessionFactory, seeded: SeededOrgs, invitations: dict[str, uuid.UUID]
) -> None:
    async with tenant_session(app_session_factory, seeded.org_a) as session:
        ids = (await session.execute(text("SELECT id FROM invitations"))).scalars().all()
    assert ids == [invitations["a"]]


async def test_an_org_cannot_touch_another_orgs_invitations(
    app_session_factory: SessionFactory,
    admin_engine: AsyncEngine,
    seeded: SeededOrgs,
    invitations: dict[str, uuid.UUID],
) -> None:
    async with tenant_session(app_session_factory, seeded.org_a) as session:
        updated = await session.execute(
            text("UPDATE invitations SET role = 'admin' WHERE id = :id"), {"id": invitations["b"]}
        )
        deleted = await session.execute(
            text("DELETE FROM invitations WHERE id = :id"), {"id": invitations["b"]}
        )
    assert updated.rowcount == 0  # type: ignore[attr-defined]
    assert deleted.rowcount == 0  # type: ignore[attr-defined]
    async with admin_engine.connect() as conn:
        role = (
            await conn.execute(
                text("SELECT role FROM invitations WHERE id = :id"), {"id": invitations["b"]}
            )
        ).scalar_one()
    assert role == "member"


async def test_an_invitation_cannot_be_created_for_another_org(
    app_session_factory: SessionFactory, seeded: SeededOrgs
) -> None:
    with pytest.raises(DBAPIError, match="row-level security"):
        async with tenant_session(app_session_factory, seeded.org_a) as session:
            await session.execute(
                text(
                    "INSERT INTO invitations "
                    "(organization_id, email, role, token_hash, expires_at) "
                    "VALUES (:o, 'x@example.com', 'admin', :h, now() + interval '1 day')"
                ),
                {"o": seeded.org_b, "h": digest("forged")},
            )


async def test_the_token_lookup_works_without_context_and_returns_one_row(
    app_session_factory: SessionFactory, seeded: SeededOrgs, invitations: dict[str, uuid.UUID]
) -> None:
    async with app_session_factory() as session, session.begin():
        repo = IdentityRepository(session)
        found = await repo.find_invitation(digest("token-b"))
        assert found is not None
        assert (found.id, found.organization_id, found.role) == (
            invitations["b"],
            seeded.org_b,
            "member",
        )
        assert found.accepted_at is None
        assert await repo.find_invitation(digest("no-such-token")) is None
        assert await repo.find_invitation("") is None


async def test_the_token_lookup_takes_the_hash_not_the_raw_token(
    app_session_factory: SessionFactory, invitations: dict[str, uuid.UUID]
) -> None:
    async with app_session_factory() as session, session.begin():
        assert await IdentityRepository(session).find_invitation("token-b") is None


async def test_the_token_lookup_is_not_callable_by_public(app_engine: AsyncEngine) -> None:
    async with app_engine.connect() as conn:
        allowed = (
            await conn.execute(
                text(
                    "SELECT has_function_privilege("
                    "'public', 'auth_find_invitation(text)', 'EXECUTE')"
                )
            )
        ).scalar_one()
    assert allowed is False


async def test_invitations_are_forced_rls_and_not_owned_by_the_runtime_role(
    app_engine: AsyncEngine,
) -> None:
    async with app_engine.connect() as conn:
        flags = (
            await conn.execute(
                text(
                    "SELECT relrowsecurity, relforcerowsecurity, "
                    "pg_get_userbyid(relowner) <> current_user "
                    "FROM pg_class WHERE relname = 'invitations'"
                )
            )
        ).one()
    assert tuple(flags) == (True, True, True)


async def test_a_user_context_alone_does_not_reveal_other_orgs_invitations(
    app_session_factory: SessionFactory, seeded: SeededOrgs, invitations: dict[str, uuid.UUID]
) -> None:
    async with app_session_factory() as session, session.begin():
        await set_context(session, user_id=seeded.user_1)  # a user, but no organization
        count = (await session.execute(text("SELECT count(*) FROM invitations"))).scalar_one()
    assert count == 0
