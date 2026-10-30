import asyncio

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.db import models  # noqa: F401
from app.db.base import Base
from tests import db_utils


async def _tables(url: str) -> set[str]:
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            rows = await conn.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            )
            return {r[0] for r in rows}
    finally:
        await engine.dispose()


def test_migrations_run_up_down_and_up_again(database: db_utils.DbUrls) -> None:
    urls = db_utils.provision_database(migrate=False)
    try:
        db_utils.upgrade(urls, "head")
        assert {"organizations", "users", "memberships"} <= asyncio.run(_tables(urls.owner))

        db_utils.downgrade(urls, "base")
        assert asyncio.run(_tables(urls.owner)) <= {"alembic_version"}

        db_utils.upgrade(urls, "head")
        assert {"organizations", "users", "memberships"} <= asyncio.run(_tables(urls.owner))
    finally:
        db_utils.drop_database(urls)


async def _schema_diff(url: str) -> list[object]:
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.connect() as conn:

            def diff(sync_conn: Connection) -> list[object]:
                ctx = MigrationContext.configure(sync_conn)
                return list(compare_metadata(ctx, Base.metadata))

            return await conn.run_sync(diff)
    finally:
        await engine.dispose()


def test_migration_matches_models(database: db_utils.DbUrls) -> None:
    assert asyncio.run(_schema_diff(database.owner)) == []
