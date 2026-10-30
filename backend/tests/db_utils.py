"""Helpers that provision throwaway PostgreSQL databases for tests.

Tests need a real PostgreSQL (no mocking, see PLAN.md section 13). Point TEST_DATABASE_URL at a
superuser connection, e.g. postgresql+asyncpg://postgres:postgres@localhost:5432/postgres.
Dedicated roles are created so existing dev roles and databases are never touched.
"""

import asyncio
import os
import uuid
from dataclasses import dataclass
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

BACKEND_DIR = Path(__file__).resolve().parents[1]

ADMIN_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/postgres"
)
OWNER_ROLE = "tf_test_owner"
APP_ROLE = "tf_test_app"
ROLE_PASSWORD = "tf_test_password"


@dataclass(frozen=True)
class DbUrls:
    name: str
    admin: str  # superuser: bypasses RLS, used only to seed and inspect
    owner: str  # table owner: runs migrations
    app: str  # runtime role: the one RLS must constrain


def _url(database: str, user: str | None = None, password: str | None = None) -> str:
    url = make_url(ADMIN_URL).set(database=database)
    if user:
        url = url.set(username=user, password=password)
    return url.render_as_string(hide_password=False)


async def _run_admin(statements: list[str], database: str = "postgres") -> None:
    engine = create_async_engine(_url(database), isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            for stmt in statements:
                await conn.execute(text(stmt))
    finally:
        await engine.dispose()


def _create_role_sql(role: str) -> str:
    return (
        f"DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{role}') THEN "
        f"CREATE ROLE {role} LOGIN PASSWORD '{ROLE_PASSWORD}' "
        f"NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS; END IF; END $$"
    )


def server_available() -> bool:
    try:
        asyncio.run(_run_admin(["SELECT 1"]))
    except Exception:
        return False
    return True


def provision_database(migrate: bool = True) -> DbUrls:
    name = f"taskflow_test_{uuid.uuid4().hex[:10]}"
    asyncio.run(
        _run_admin(
            [
                _create_role_sql(OWNER_ROLE),
                _create_role_sql(APP_ROLE),
                f"CREATE DATABASE {name} OWNER {OWNER_ROLE}",
                f"REVOKE ALL ON DATABASE {name} FROM PUBLIC",
                f"GRANT CONNECT ON DATABASE {name} TO {OWNER_ROLE}, {APP_ROLE}",
            ]
        )
    )
    asyncio.run(_run_admin([f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}"], database=name))
    urls = DbUrls(
        name=name,
        admin=_url(name),
        owner=_url(name, OWNER_ROLE, ROLE_PASSWORD),
        app=_url(name, APP_ROLE, ROLE_PASSWORD),
    )
    if migrate:
        upgrade(urls, "head")
    return urls


def drop_database(urls: DbUrls) -> None:
    asyncio.run(_run_admin([f"DROP DATABASE IF EXISTS {urls.name} WITH (FORCE)"]))


def alembic_config(urls: DbUrls) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    cfg.set_main_option("sqlalchemy.url", urls.owner.replace("%", "%%"))
    cfg.set_main_option("app_role", APP_ROLE)
    return cfg


def upgrade(urls: DbUrls, revision: str) -> None:
    command.upgrade(alembic_config(urls), revision)


def downgrade(urls: DbUrls, revision: str) -> None:
    command.downgrade(alembic_config(urls), revision)
