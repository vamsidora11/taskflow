"""Authentication security properties from PLAN.md section 7 and the Phase 2 criteria."""

import asyncio
import hashlib
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.api.deps import get_factory
from app.core.config import settings
from tests.integration.test_auth_api import COOKIE, PASSWORD, bearer, signup, unique_email


def replay(api: AsyncClient, token: str) -> AsyncClient:
    """A fresh client (no cookie jar) that presents one specific refresh token."""
    client = AsyncClient(
        transport=api._transport,  # same app and database
        base_url="https://test",
        headers={"Cookie": f"{COOKIE}={token}"},
    )
    return client


async def family_rows(admin_engine: AsyncEngine, raw_token: str) -> list[Any]:
    digest = hashlib.sha256(raw_token.encode()).hexdigest()
    async with admin_engine.connect() as conn:
        return list(
            (
                await conn.execute(
                    text(
                        "SELECT t.* FROM refresh_tokens t WHERE t.family_id = "
                        "(SELECT family_id FROM refresh_tokens WHERE token_hash = :h) "
                        "ORDER BY t.created_at"
                    ),
                    {"h": digest},
                )
            ).all()
        )


async def test_reusing_a_rotated_refresh_token_revokes_the_whole_family(
    api: AsyncClient, admin_engine: AsyncEngine
) -> None:
    await signup(api)
    stolen = api.cookies[COOKIE]

    rotated = await api.post("/api/v1/auth/refresh")  # the legitimate client rotates
    assert rotated.status_code == 200
    legitimate = api.cookies[COOKIE]

    async with replay(api, stolen) as attacker:  # the attacker replays the old token
        resp = await attacker.post("/api/v1/auth/refresh")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "INVALID_REFRESH_TOKEN"

    # The revocation must have been committed, so the newest legitimate token is dead too.
    rows = await family_rows(admin_engine, legitimate)
    assert len(rows) == 2
    assert all(r.revoked_at is not None for r in rows)
    async with replay(api, legitimate) as victim:
        assert (await victim.post("/api/v1/auth/refresh")).status_code == 401


async def test_concurrent_refreshes_of_one_token_cannot_both_succeed(api: AsyncClient) -> None:
    await signup(api)
    token = api.cookies[COOKIE]

    async def attempt() -> int:
        async with replay(api, token) as client:
            return (await client.post("/api/v1/auth/refresh")).status_code

    statuses = sorted(await asyncio.gather(attempt(), attempt()))
    assert statuses == [200, 401]


async def test_refresh_tokens_are_stored_only_as_sha256_hashes(
    api: AsyncClient, admin_engine: AsyncEngine
) -> None:
    await signup(api)
    raw = api.cookies[COOKIE]
    async with admin_engine.connect() as conn:
        by_raw = (
            await conn.execute(
                text("SELECT count(*) FROM refresh_tokens WHERE token_hash = :t"), {"t": raw}
            )
        ).scalar_one()
        by_hash = (
            await conn.execute(
                text("SELECT count(*) FROM refresh_tokens WHERE token_hash = :t"),
                {"t": hashlib.sha256(raw.encode()).hexdigest()},
            )
        ).scalar_one()
    assert (by_raw, by_hash) == (0, 1)


async def test_passwords_are_stored_as_argon2id_and_never_returned(
    api: AsyncClient, admin_engine: AsyncEngine
) -> None:
    session = await signup(api)
    async with admin_engine.connect() as conn:
        stored = (
            await conn.execute(
                text("SELECT password_hash FROM users WHERE email = :e"), {"e": session["email"]}
            )
        ).scalar_one()
    assert stored.startswith("$argon2id$")
    assert PASSWORD not in stored

    login = await api.post(
        "/api/v1/auth/login", json={"email": session["email"], "password": PASSWORD}
    )
    me = await api.get("/api/v1/auth/me", headers=bearer(session["access_token"]))
    for body in (session, login.text, me.text):
        assert PASSWORD not in str(body)
        assert "argon2" not in str(body)
        assert "password_hash" not in str(body)


async def test_login_failures_are_indistinguishable(api: AsyncClient) -> None:
    session = await signup(api)
    api.cookies.clear()
    wrong_password = await api.post(
        "/api/v1/auth/login",
        json={"email": session["email"], "password": "definitely-the-wrong-one"},
    )
    unknown_email = await api.post(
        "/api/v1/auth/login", json={"email": unique_email(), "password": "definitely-the-wrong-one"}
    )
    assert wrong_password.status_code == unknown_email.status_code == 401
    for resp in (wrong_password, unknown_email):
        assert COOKIE not in resp.headers.get("set-cookie", "")
    a, b = wrong_password.json()["error"], unknown_email.json()["error"]
    assert (a["code"], a["message"]) == (b["code"], b["message"])
    assert a["code"] == "INVALID_CREDENTIALS"


async def test_a_disabled_account_cannot_log_in_and_looks_like_a_wrong_password(
    api: AsyncClient, admin_engine: AsyncEngine
) -> None:
    session = await signup(api)
    async with admin_engine.begin() as conn:
        await conn.execute(
            text("UPDATE users SET is_active = false WHERE email = :e"), {"e": session["email"]}
        )
    resp = await api.post(
        "/api/v1/auth/login", json={"email": session["email"], "password": PASSWORD}
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "INVALID_CREDENTIALS"
    # ...and an already-issued access token stops working too.
    assert (
        await api.get("/api/v1/auth/me", headers=bearer(session["access_token"]))
    ).status_code == 401


async def test_removing_a_member_invalidates_their_access_token_and_refresh_token(
    api: AsyncClient, admin_engine: AsyncEngine
) -> None:
    session = await signup(api)
    assert (
        await api.get("/api/v1/auth/me", headers=bearer(session["access_token"]))
    ).status_code == 200
    async with admin_engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM memberships WHERE organization_id = :o"),
            {"o": session["organization_id"]},
        )
    me = await api.get("/api/v1/auth/me", headers=bearer(session["access_token"]))
    assert me.status_code == 401
    assert me.json()["error"]["code"] == "INVALID_TOKEN"  # same answer as a forged token
    assert (await api.post("/api/v1/auth/refresh")).status_code == 401


async def test_an_expired_refresh_token_is_rejected(
    api: AsyncClient, admin_engine: AsyncEngine
) -> None:
    await signup(api)
    digest = hashlib.sha256(api.cookies[COOKIE].encode()).hexdigest()
    async with admin_engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE refresh_tokens SET expires_at = now() - interval '1 minute' "
                "WHERE token_hash = :h"
            ),
            {"h": digest},
        )
    assert (await api.post("/api/v1/auth/refresh")).status_code == 401


async def test_switching_organization_revokes_the_previous_session(
    api: AsyncClient, admin_engine: AsyncEngine
) -> None:
    first = await signup(api, org="First")
    me = await api.get("/api/v1/auth/me", headers=bearer(first["access_token"]))
    user_id = me.json()["user"]["id"]
    old_cookie = api.cookies[COOKIE]

    api.cookies.clear()
    second = await signup(api, org="Second")
    async with admin_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO memberships (organization_id, user_id, role) VALUES (:o, :u, 'member')"
            ),
            {"o": second["organization_id"], "u": user_id},
        )

    async with replay(api, old_cookie) as client:
        resp = await client.post(
            "/api/v1/auth/switch-org",
            json={"organization_id": second["organization_id"]},
            headers=bearer(first["access_token"]),
        )
        assert resp.status_code == 200
        new_cookie = resp.cookies[COOKIE]

    async with replay(api, new_cookie) as client:  # the new session is bound to org two
        assert (await client.post("/api/v1/auth/refresh")).json()["organization_id"] == second[
            "organization_id"
        ]
    async with replay(api, old_cookie) as client:  # the old session is gone
        assert (await client.post("/api/v1/auth/refresh")).status_code == 401
    rows = await family_rows(admin_engine, old_cookie)
    assert all(r.revoked_at is not None for r in rows)


async def test_a_user_cannot_read_another_tenants_account_data(api: AsyncClient) -> None:
    alice = await signup(api, org="Alice Org")
    api.cookies.clear()
    bob = await signup(api, org="Bob Org")
    me_alice = (await api.get("/api/v1/auth/me", headers=bearer(alice["access_token"]))).json()
    me_bob = (await api.get("/api/v1/auth/me", headers=bearer(bob["access_token"]))).json()
    assert [o["id"] for o in me_alice["organizations"]] == [alice["organization_id"]]
    assert [o["id"] for o in me_bob["organizations"]] == [bob["organization_id"]]
    assert bob["organization_id"] not in str(me_alice)
    assert alice["organization_id"] not in str(me_bob)


@pytest.mark.parametrize("path", ["/api/v1/auth/signup", "/api/v1/auth/login"])
async def test_auth_responses_never_set_a_cookie_on_failure(api: AsyncClient, path: str) -> None:
    resp = await api.post(path, json={"email": "not-an-email"})
    assert resp.status_code == 422
    assert "set-cookie" not in resp.headers


async def test_unhandled_errors_do_not_leak_details(database: Any) -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.main import create_app

    # Point the app at an unreachable database so the route blows up with a driver error.
    engine = create_async_engine("postgresql+asyncpg://nobody:secret-pw@127.0.0.1:1/none")
    app = create_app()
    app.dependency_overrides[get_factory] = lambda: async_sessionmaker(engine)
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="https://test") as client:
        resp = await client.post(
            "/api/v1/auth/login", json={"email": "a@example.com", "password": "whatever-123456"}
        )
    await engine.dispose()
    assert resp.status_code == 500
    assert resp.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "secret-pw" not in resp.text
    assert "Traceback" not in resp.text
    assert settings.jwt_secret_key not in resp.text
