import uuid

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.db.session import SessionFactory, tenant_session
from app.repositories.membership import MembershipRepository
from tests.conftest import SeededOrgs


async def test_list_and_get_are_scoped_to_the_organization(
    app_session_factory: SessionFactory, seeded: SeededOrgs
) -> None:
    async with tenant_session(app_session_factory, seeded.org_a) as session:
        repo = MembershipRepository(session, seeded.org_a)
        listed = await repo.list()
        assert {m.organization_id for m in listed} == {seeded.org_a}
        assert len(listed) == 2
        assert (await repo.get(seeded.membership_a1)) is not None
        assert (await repo.get(seeded.membership_b3)) is None
        assert (await repo.get_by_user_id(seeded.user_3)) is None
        assert (await repo.get_by_user_id(seeded.user_1)) is not None


async def test_add_sets_the_organization(
    app_session_factory: SessionFactory, seeded: SeededOrgs
) -> None:
    async with tenant_session(app_session_factory, seeded.org_a) as session:
        repo = MembershipRepository(session, seeded.org_a)
        created = await repo.add(user_id=seeded.user_3, role="member")
        assert created.organization_id == seeded.org_a
        assert isinstance(created.id, uuid.UUID)
    async with tenant_session(app_session_factory, seeded.org_a) as session:
        assert len(await MembershipRepository(session, seeded.org_a).list()) == 3


async def test_repository_filters_even_without_rls(
    admin_engine: AsyncEngine, seeded: SeededOrgs
) -> None:
    """Defense in depth: a superuser connection bypasses RLS, but the repository's own
    organization filter must still keep results to one tenant."""
    factory = async_sessionmaker(admin_engine, expire_on_commit=False)
    async with factory() as session:
        repo = MembershipRepository(session, seeded.org_a)
        assert {m.organization_id for m in await repo.list()} == {seeded.org_a}
        assert await repo.get(seeded.membership_b3) is None
