"""The audit log is append-only in the database and never holds secrets (PLAN.md section 8)."""

import re
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.session import SessionFactory, tenant_session
from tests.conftest import SeededOrgs
from tests.helpers import (
    COOKIE,
    PASSWORD,
    Mailbox,
    bearer,
    create_org,
    make_board,
    make_task,
    signup,
    unique_email,
)


@pytest.fixture
async def log_rows(admin_engine: AsyncEngine, seeded: SeededOrgs) -> dict[str, int]:
    ids: dict[str, int] = {}
    async with admin_engine.begin() as conn:
        for key, org in (("a", seeded.org_a), ("b", seeded.org_b)):
            ids[key] = (
                await conn.execute(
                    text(
                        "INSERT INTO audit_logs (organization_id, action, entity_type, metadata) "
                        "VALUES (:o, 'test.event', 'test', '{}') RETURNING id"
                    ),
                    {"o": org},
                )
            ).scalar_one()
    return ids


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE audit_logs SET action = 'tampered'",
        "DELETE FROM audit_logs",
        "TRUNCATE audit_logs",
        "DROP TABLE audit_logs",
        "ALTER TABLE audit_logs DISABLE ROW LEVEL SECURITY",
    ],
)
async def test_the_runtime_role_cannot_rewrite_history(
    app_session_factory: SessionFactory, seeded: SeededOrgs, log_rows: dict[str, int], sql: str
) -> None:
    with pytest.raises(DBAPIError, match="permission denied|must be owner"):
        async with tenant_session(app_session_factory, seeded.org_a) as session:
            await session.execute(text(sql))


async def test_the_runtime_role_holds_exactly_select_and_insert(app_engine: AsyncEngine) -> None:
    async with app_engine.connect() as conn:
        granted = {
            p: (
                await conn.execute(
                    text("SELECT has_table_privilege(current_user, 'audit_logs', :p)"), {"p": p}
                )
            ).scalar_one()
            for p in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER")
        }
    assert granted == {
        "SELECT": True,
        "INSERT": True,
        "UPDATE": False,
        "DELETE": False,
        "TRUNCATE": False,
        "REFERENCES": False,
        "TRIGGER": False,
    }


async def test_an_organization_reads_only_its_own_rows(
    app_session_factory: SessionFactory, seeded: SeededOrgs, log_rows: dict[str, int]
) -> None:
    async with tenant_session(app_session_factory, seeded.org_a) as session:
        ids = (await session.execute(text("SELECT id FROM audit_logs"))).scalars().all()
    assert ids == [log_rows["a"]]


async def test_no_context_reads_nothing_and_cannot_write_for_another_org(
    app_engine: AsyncEngine,
    app_session_factory: SessionFactory,
    seeded: SeededOrgs,
    log_rows: dict[str, int],
) -> None:
    async with app_engine.connect() as conn:
        assert (await conn.execute(text("SELECT count(*) FROM audit_logs"))).scalar_one() == 0
    with pytest.raises(DBAPIError, match="row-level security"):
        async with tenant_session(app_session_factory, seeded.org_a) as session:
            await session.execute(
                text(
                    "INSERT INTO audit_logs (organization_id, action, entity_type, metadata) "
                    "VALUES (:o, 'x', 'x', '{}')"
                ),
                {"o": seeded.org_b},
            )


async def test_a_system_event_can_be_written_by_anyone_but_read_by_no_tenant(
    app_session_factory: SessionFactory, admin_engine: AsyncEngine, seeded: SeededOrgs
) -> None:
    marker = uuid.uuid4().hex
    async with tenant_session(app_session_factory, seeded.org_a) as session:
        await session.execute(
            text(
                "INSERT INTO audit_logs (organization_id, action, entity_type, metadata) "
                "VALUES (NULL, :m, 'system', '{}')"
            ),
            {"m": marker},
        )
        seen = (
            await session.execute(
                text("SELECT count(*) FROM audit_logs WHERE action = :m"), {"m": marker}
            )
        ).scalar_one()
    assert seen == 0
    async with admin_engine.connect() as conn:
        stored = (
            await conn.execute(
                text("SELECT count(*) FROM audit_logs WHERE action = :m"), {"m": marker}
            )
        ).scalar_one()
    assert stored == 1


async def test_audit_rows_never_contain_passwords_tokens_or_hashes(
    api: AsyncClient, admin_engine: AsyncEngine, mailbox: Mailbox
) -> None:
    """Drive every auth, member and content flow, then scan everything the log stored."""
    org = await create_org(api, admin_engine)
    secrets_seen: set[str] = {PASSWORD, "wrong password guess"}

    api.cookies.clear()
    login = await api.post(
        "/api/v1/auth/login", json={"email": org.admin.email, "password": PASSWORD}
    )
    secrets_seen |= {login.json()["access_token"], api.cookies[COOKIE]}
    stolen = api.cookies[COOKIE]
    await api.post("/api/v1/auth/refresh")
    await api.post(
        "/api/v1/auth/login", json={"email": org.admin.email, "password": "wrong password guess"}
    )
    await api.post(
        "/api/v1/auth/login", json={"email": "password@example.com", "password": PASSWORD}
    )
    async with AsyncClient(
        transport=api._transport, base_url="https://test", headers={"Cookie": f"{COOKIE}={stolen}"}
    ) as attacker:
        await attacker.post("/api/v1/auth/refresh")

    invitee = unique_email("inv")
    await api.post(
        "/api/v1/org/invitations",
        json={"email": invitee, "role": "member"},
        headers=org.admin.headers,
    )
    token = mailbox.token_for(invitee)
    secrets_seen.add(token)
    accepted = await api.post(
        f"/api/v1/org/invitations/{token}/accept", json={"password": PASSWORD, "full_name": "New"}
    )
    secrets_seen.add(accepted.json()["access_token"])

    board = await make_board(api, org.admin, "B")
    task = await make_task(api, org.admin, board["id"], "T", description="body")
    await api.patch(
        f"/api/v1/tasks/{task['id']}",
        json={"title": "T2", "description": "changed"},
        headers=org.admin.headers,
    )
    await api.post(
        f"/api/v1/tasks/{task['id']}/comments",
        json={"body": "a comment"},
        headers=org.member.headers,
    )
    await signup(api, org="Another")

    async with admin_engine.connect() as conn:
        rows = (
            await conn.execute(text("SELECT action, metadata::text AS m FROM audit_logs"))
        ).all()
        argon = (await conn.execute(text("SELECT password_hash FROM users LIMIT 1"))).scalar_one()
    assert len(rows) > 15
    blob = " ".join(r.m for r in rows)
    for secret in secrets_seen | {argon}:
        assert secret not in blob, "a secret leaked into the audit log"
    assert not re.search(r"argon2|\$2[aby]\$|eyJ[A-Za-z0-9_-]{10,}", blob)
    assert not re.search(
        r'"[^"]*(password|token|secret|hash|authorization)[^"]*"\s*:\s*"(?!\[REDACTED\]|[0-9a-f]{12}")',
        blob,
        re.IGNORECASE,
    )
    assert (
        PASSWORD
        not in (
            await api.get("/api/v1/audit-logs", params={"limit": 100}, headers=org.admin.headers)
        ).text
    )
    assert bearer("x")  # keep the helper import honest
