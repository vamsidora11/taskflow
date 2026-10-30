import os
import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.deps import get_factory
from app.db.session import SessionFactory
from app.main import create_app
from tests.db_utils import DbUrls, drop_database, provision_database, server_available


def _skip_or_fail(reason: str) -> None:
    # CI must never silently skip the database suites.
    if os.environ.get("CI"):
        pytest.fail(reason)
    pytest.skip(reason)


@pytest.fixture(scope="session")
def database() -> Iterator[DbUrls]:
    """A fresh, fully migrated database for the whole test session."""
    if not server_available():
        _skip_or_fail("PostgreSQL not reachable; set TEST_DATABASE_URL (superuser URL)")
    urls = provision_database()
    yield urls
    drop_database(urls)


@pytest.fixture
async def admin_engine(database: DbUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(database.admin, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest.fixture
async def app_engine(database: DbUrls) -> AsyncIterator[AsyncEngine]:
    """Runtime role engine with a single pooled connection, so any setting that leaked
    from one transaction would be visible to the next test query."""
    engine = create_async_engine(database.app, pool_size=1, max_overflow=0)
    yield engine
    await engine.dispose()


@pytest.fixture
def app_session_factory(app_engine: AsyncEngine) -> SessionFactory:
    return async_sessionmaker(app_engine, expire_on_commit=False)


@pytest.fixture
async def api(database: DbUrls) -> AsyncIterator[AsyncClient]:
    """The real app wired to the test database as the non-owner runtime role.

    https base URL so the Secure refresh cookie is stored and replayed like a browser would.
    The pool has room for two connections because switch-org uses a tenant-scoped session and
    an auth session in the same request.
    """
    engine = create_async_engine(database.app, pool_size=5, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    app = create_app()
    app.dependency_overrides[get_factory] = lambda: factory
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://test") as client:
        yield client
    await engine.dispose()


@dataclass(frozen=True)
class SeededOrgs:
    org_a: uuid.UUID
    org_b: uuid.UUID
    user_1: uuid.UUID  # admin of A
    user_2: uuid.UUID  # member of A
    user_3: uuid.UUID  # admin of B
    membership_a1: uuid.UUID
    membership_b3: uuid.UUID


@pytest.fixture
async def seeded(admin_engine: AsyncEngine) -> AsyncIterator[SeededOrgs]:
    """Two organizations with memberships. Seeded as superuser (bypasses RLS) and removed
    afterwards; deleting organizations and users cascades to memberships."""
    ids = {k: uuid.uuid4() for k in ("org_a", "org_b", "u1", "u2", "u3", "m_a1", "m_a2", "m_b3")}
    tag = uuid.uuid4().hex[:8]
    async with admin_engine.begin() as conn:
        for key, label in (("org_a", "Org A"), ("org_b", "Org B")):
            await conn.execute(
                text("INSERT INTO organizations (id, name, slug) VALUES (:id, :n, :s)"),
                {"id": ids[key], "n": label, "s": f"{key}-{tag}"},
            )
        for key in ("u1", "u2", "u3"):
            await conn.execute(
                text(
                    "INSERT INTO users (id, email, password_hash, full_name) "
                    "VALUES (:id, :e, 'x', :n)"
                ),
                {"id": ids[key], "e": f"{key}-{tag}@example.com", "n": key},
            )
        for mid, org, user, role in (
            ("m_a1", "org_a", "u1", "admin"),
            ("m_a2", "org_a", "u2", "member"),
            ("m_b3", "org_b", "u3", "admin"),
        ):
            await conn.execute(
                text(
                    "INSERT INTO memberships (id, organization_id, user_id, role) "
                    "VALUES (:id, :o, :u, :r)"
                ),
                {"id": ids[mid], "o": ids[org], "u": ids[user], "r": role},
            )
    yield SeededOrgs(
        org_a=ids["org_a"],
        org_b=ids["org_b"],
        user_1=ids["u1"],
        user_2=ids["u2"],
        user_3=ids["u3"],
        membership_a1=ids["m_a1"],
        membership_b3=ids["m_b3"],
    )
    async with admin_engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM organizations WHERE id IN (:a, :b)"),
            {"a": ids["org_a"], "b": ids["org_b"]},
        )
        await conn.execute(
            text("DELETE FROM users WHERE id IN (:a, :b, :c)"),
            {"a": ids["u1"], "b": ids["u2"], "c": ids["u3"]},
        )
