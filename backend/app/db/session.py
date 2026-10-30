import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings

SessionFactory = async_sessionmaker[AsyncSession]

_SET_SETTING = text("SELECT set_config(:name, :value, true)")


def create_engine(url: str) -> AsyncEngine:
    return create_async_engine(url, pool_pre_ping=True)


@lru_cache
def get_engine() -> AsyncEngine:
    """Engine for the runtime role (app_user). Migrations use a separate owner connection."""
    return create_engine(settings.database_url)


@lru_cache
def get_session_factory() -> SessionFactory:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def set_context(
    session: AsyncSession, *, org_id: uuid.UUID | None = None, user_id: uuid.UUID | None = None
) -> None:
    """Set the transaction-local identity that the RLS policies read.

    `set_config(..., true)` lasts until the current transaction commits or rolls back, so
    it can never leak to the next request that reuses the pooled connection.
    """
    if org_id is not None:
        await session.execute(_SET_SETTING, {"name": "app.current_org_id", "value": str(org_id)})
    if user_id is not None:
        await session.execute(_SET_SETTING, {"name": "app.current_user_id", "value": str(user_id)})


@asynccontextmanager
async def tenant_session(
    factory: SessionFactory, org_id: uuid.UUID, user_id: uuid.UUID | None = None
) -> AsyncIterator[AsyncSession]:
    """Open a session whose single transaction is scoped to one organization (and user).

    The transaction commits when the block exits cleanly and rolls back on error; code inside
    must not call `session.commit()`.
    """
    async with factory() as session, session.begin():
        await set_context(session, org_id=org_id, user_id=user_id)
        yield session
