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

_SET_ORG = text("SELECT set_config('app.current_org_id', :org_id, true)")


def create_engine(url: str) -> AsyncEngine:
    return create_async_engine(url, pool_pre_ping=True)


@lru_cache
def get_engine() -> AsyncEngine:
    """Engine for the runtime role (app_user). Migrations use a separate owner connection."""
    return create_engine(settings.database_url)


@lru_cache
def get_session_factory() -> SessionFactory:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


@asynccontextmanager
async def tenant_session(factory: SessionFactory, org_id: uuid.UUID) -> AsyncIterator[AsyncSession]:
    """Open a session whose transaction is scoped to one organization for RLS.

    `set_config(..., true)` is transaction-local, so the setting disappears on commit or
    rollback. The transaction commits when the block exits cleanly and rolls back on error;
    code inside must not call `session.commit()`.
    """
    async with factory() as session, session.begin():
        await session.execute(_SET_ORG, {"org_id": str(org_id)})
        yield session
