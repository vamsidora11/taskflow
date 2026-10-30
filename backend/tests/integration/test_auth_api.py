import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import settings

PASSWORD = "correct horse battery staple"
COOKIE = settings.refresh_cookie_name


def unique_email() -> str:
    return f"user-{uuid.uuid4().hex[:10]}@example.com"


async def signup(
    api: AsyncClient, email: str | None = None, org: str = "Acme Inc"
) -> dict[str, Any]:
    email = email or unique_email()
    resp = await api.post(
        "/api/v1/auth/signup",
        json={
            "organization_name": org,
            "email": email,
            "password": PASSWORD,
            "full_name": "Ada Lovelace",
        },
    )
    assert resp.status_code == 201, resp.text
    return {**resp.json(), "email": email}


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_signup_returns_access_token_and_sets_refresh_cookie(api: AsyncClient) -> None:
    resp = await api.post(
        "/api/v1/auth/signup",
        json={
            "organization_name": "Acme Inc",
            "email": unique_email(),
            "password": PASSWORD,
            "full_name": "Ada",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["role"] == "admin"
    assert body["expires_in"] == 900
    assert "refresh_token" not in body

    cookie = resp.headers["set-cookie"].lower()
    assert f"{COOKIE}=" in cookie
    assert "httponly" in cookie
    assert "secure" in cookie
    assert "samesite=strict" in cookie
    assert "path=/api/v1/auth" in cookie


async def test_me_returns_user_and_active_organization(api: AsyncClient) -> None:
    session = await signup(api, org="Acme Inc")
    resp = await api.get("/api/v1/auth/me", headers=bearer(session["access_token"]))
    assert resp.status_code == 200
    body = resp.json()
    assert body["user"]["email"] == session["email"]
    assert body["active_organization"]["id"] == session["organization_id"]
    assert body["active_organization"]["role"] == "admin"
    assert body["active_organization"]["slug"].startswith("acme-inc-")
    assert [o["id"] for o in body["organizations"]] == [session["organization_id"]]


async def test_login_succeeds_case_insensitively(api: AsyncClient) -> None:
    session = await signup(api)
    api.cookies.clear()
    resp = await api.post(
        "/api/v1/auth/login",
        json={"email": session["email"].upper(), "password": PASSWORD},
    )
    assert resp.status_code == 200
    assert resp.json()["organization_id"] == session["organization_id"]
    assert COOKIE in resp.headers["set-cookie"]


async def test_signup_with_a_taken_email_is_409_in_any_case(api: AsyncClient) -> None:
    session = await signup(api)
    resp = await api.post(
        "/api/v1/auth/signup",
        json={
            "organization_name": "Other",
            "email": session["email"].upper(),
            "password": PASSWORD,
            "full_name": "Someone",
        },
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "EMAIL_ALREADY_REGISTERED"


async def test_signup_validation_uses_the_error_envelope_and_never_echoes_the_password(
    api: AsyncClient,
) -> None:
    resp = await api.post(
        "/api/v1/auth/signup",
        json={
            "organization_name": "Acme",
            "email": unique_email(),
            "password": "short-pw",
            "full_name": "Ada",
        },
    )
    assert resp.status_code == 422
    error = resp.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert "password" in error["message"]
    assert "short-pw" not in resp.text
    assert error["request_id"] == resp.headers["x-request-id"]


async def test_refresh_rotates_the_token_and_returns_a_new_access_token(api: AsyncClient) -> None:
    session = await signup(api)
    first_cookie = api.cookies[COOKIE]

    resp = await api.post("/api/v1/auth/refresh")
    assert resp.status_code == 200
    assert resp.json()["access_token"] != session["access_token"]
    assert api.cookies[COOKIE] != first_cookie

    me = await api.get("/api/v1/auth/me", headers=bearer(resp.json()["access_token"]))
    assert me.status_code == 200


async def test_refresh_without_a_cookie_is_401(api: AsyncClient) -> None:
    resp = await api.post("/api/v1/auth/refresh")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "INVALID_REFRESH_TOKEN"


async def test_logout_revokes_the_session_and_clears_the_cookie(api: AsyncClient) -> None:
    await signup(api)
    cookie_value = api.cookies[COOKIE]

    resp = await api.post("/api/v1/auth/logout")
    assert resp.status_code == 204
    assert COOKIE not in api.cookies  # server expired it

    api.headers["Cookie"] = f"{COOKIE}={cookie_value}"
    assert (await api.post("/api/v1/auth/refresh")).status_code == 401


async def test_logout_without_a_session_still_returns_204(api: AsyncClient) -> None:
    assert (await api.post("/api/v1/auth/logout")).status_code == 204


async def test_switch_org_issues_a_token_for_another_organization(
    api: AsyncClient, admin_engine: AsyncEngine
) -> None:
    ada = await signup(api, org="Ada Org")
    api.cookies.clear()
    other = await signup(api, org="Other Org")
    ada_id = (await api.get("/api/v1/auth/me", headers=bearer(ada["access_token"]))).json()["user"][
        "id"
    ]
    async with admin_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO memberships (organization_id, user_id, role) "
                "VALUES (:org, :user, 'member')"
            ),
            {"org": other["organization_id"], "user": ada_id},
        )

    api.cookies.clear()
    login = await api.post("/api/v1/auth/login", json={"email": ada["email"], "password": PASSWORD})
    token = login.json()["access_token"]
    assert login.json()["organization_id"] == ada["organization_id"]

    resp = await api.post(
        "/api/v1/auth/switch-org",
        json={"organization_id": other["organization_id"]},
        headers=bearer(token),
    )
    assert resp.status_code == 200
    assert resp.json()["organization_id"] == other["organization_id"]
    assert resp.json()["role"] == "member"

    me = await api.get("/api/v1/auth/me", headers=bearer(resp.json()["access_token"]))
    body = me.json()
    assert body["active_organization"]["id"] == other["organization_id"]
    assert len(body["organizations"]) == 2

    # The new refresh cookie is bound to the new organization.
    refreshed = await api.post("/api/v1/auth/refresh")
    assert refreshed.json()["organization_id"] == other["organization_id"]


async def test_switch_org_to_a_foreign_or_unknown_org_is_404(api: AsyncClient) -> None:
    mine = await signup(api, org="Mine")
    api.cookies.clear()
    theirs = await signup(api, org="Theirs")

    foreign = await api.post(
        "/api/v1/auth/switch-org",
        json={"organization_id": theirs["organization_id"]},
        headers=bearer(mine["access_token"]),
    )
    unknown = await api.post(
        "/api/v1/auth/switch-org",
        json={"organization_id": str(uuid.uuid4())},
        headers=bearer(mine["access_token"]),
    )
    assert foreign.status_code == unknown.status_code == 404
    assert foreign.json()["error"]["code"] == unknown.json()["error"]["code"]
    assert foreign.json()["error"]["message"] == unknown.json()["error"]["message"]


async def test_protected_route_without_a_token_is_401_in_the_envelope(api: AsyncClient) -> None:
    resp = await api.get("/api/v1/auth/me")
    assert resp.status_code == 401
    assert set(resp.json()["error"]) == {"code", "message", "request_id"}
    assert resp.headers["www-authenticate"] == "Bearer"


async def test_garbage_bearer_token_is_401(api: AsyncClient) -> None:
    resp = await api.get("/api/v1/auth/me", headers=bearer("not.a.jwt"))
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "INVALID_TOKEN"


async def test_expired_access_token_is_401(api: AsyncClient) -> None:
    session = await signup(api)
    claims = jwt.decode(session["access_token"], options={"verify_signature": False})
    claims["exp"] = int((datetime.now(UTC) - timedelta(seconds=5)).timestamp())
    expired = jwt.encode(claims, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    resp = await api.get("/api/v1/auth/me", headers=bearer(expired))
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "INVALID_TOKEN"


async def test_token_signed_with_the_wrong_key_is_401(api: AsyncClient) -> None:
    session = await signup(api)
    claims = jwt.decode(session["access_token"], options={"verify_signature": False})
    forged = jwt.encode(claims, "an-attacker-chosen-secret-that-is-long-enough", algorithm="HS256")
    assert (await api.get("/api/v1/auth/me", headers=bearer(forged))).status_code == 401


async def test_a_refresh_cookie_value_is_not_accepted_as_an_access_token(api: AsyncClient) -> None:
    await signup(api)
    resp = await api.get("/api/v1/auth/me", headers=bearer(api.cookies[COOKIE]))
    assert resp.status_code == 401


async def test_every_response_carries_a_request_id_and_honours_a_supplied_one(
    api: AsyncClient,
) -> None:
    assert api.headers.get("x-request-id") is None
    resp = await api.get("/health")
    assert resp.headers["x-request-id"].startswith("req_")
    supplied = await api.get("/health", headers={"X-Request-ID": "trace-123"})
    assert supplied.headers["x-request-id"] == "trace-123"
    hostile = await api.get("/health", headers={"X-Request-ID": "bad id\twith spaces"})
    assert hostile.headers["x-request-id"].startswith("req_")
