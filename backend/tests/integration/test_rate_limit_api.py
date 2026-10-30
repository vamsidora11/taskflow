from typing import Any

import pytest
from httpx import AsyncClient
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine

from app.api.deps import get_redis_client
from app.core.config import settings
from tests.helpers import PASSWORD, Mailbox, OrgSetup, bearer, create_org, signup, unique_email


@pytest.fixture
async def org(api: AsyncClient, admin_engine: AsyncEngine) -> OrgSetup:
    return await create_org(api, admin_engine)


def limit(monkeypatch: pytest.MonkeyPatch, name: str, spec: str) -> None:
    monkeypatch.setattr(settings, name, spec)


async def login(api: AsyncClient, email: str, password: str = "wrong password guess") -> Any:
    return await api.post("/api/v1/auth/login", json={"email": email, "password": password})


def assert_throttled(resp: Any, limit_value: int) -> None:
    assert resp.status_code == 429
    assert resp.json()["error"]["code"] == "RATE_LIMITED"
    assert resp.json()["error"]["request_id"] == resp.headers["x-request-id"]
    assert int(resp.headers["retry-after"]) >= 1
    assert resp.headers["x-ratelimit-limit"] == str(limit_value)
    assert resp.headers["x-ratelimit-remaining"] == "0"


async def test_brute_forcing_login_from_one_ip_is_blocked_after_the_threshold(
    api: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    limit(monkeypatch, "rate_limit_login_per_ip", "5/minute")
    statuses = [(await login(api, unique_email("guess"))).status_code for _ in range(5)]
    assert statuses == [401] * 5  # five different accounts, all merely wrong
    assert_throttled(await login(api, unique_email("guess")), 5)


async def test_even_the_correct_password_is_refused_once_the_ip_is_throttled(
    api: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = await signup(api)
    api.cookies.clear()
    limit(monkeypatch, "rate_limit_login_per_ip", "2/minute")
    await login(api, "nobody@example.com")
    await login(api, "nobody@example.com")
    blocked = await login(api, session["email"], PASSWORD)
    assert_throttled(blocked, 2)
    assert "set-cookie" not in blocked.headers


async def test_one_account_is_protected_against_distributed_guessing(
    api: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    limit(monkeypatch, "rate_limit_login_per_email", "3/15minutes")
    victim = "victim@example.com"
    assert [(await login(api, victim)).status_code for _ in range(3)] == [401] * 3
    assert_throttled(await login(api, victim), 3)
    assert_throttled(await login(api, victim.upper()), 3)  # case games do not help
    assert (await login(api, "someone-else@example.com")).status_code == 401  # others unaffected


async def test_login_responses_advertise_the_remaining_budget(
    api: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    limit(monkeypatch, "rate_limit_login_per_ip", "10/minute")
    first = await login(api, unique_email())
    second = await login(api, unique_email())
    assert first.headers["x-ratelimit-limit"] == "10"
    assert (first.headers["x-ratelimit-remaining"], second.headers["x-ratelimit-remaining"]) == (
        "9",
        "8",
    )


async def test_refresh_is_limited_per_ip(api: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    await signup(api)
    limit(monkeypatch, "rate_limit_refresh_per_ip", "2/minute")
    assert (await api.post("/api/v1/auth/refresh")).status_code == 200
    assert (await api.post("/api/v1/auth/refresh")).status_code == 200
    assert_throttled(await api.post("/api/v1/auth/refresh"), 2)


async def test_signup_is_limited_per_ip(api: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    limit(monkeypatch, "rate_limit_signup_per_ip", "2/minute")
    await signup(api)
    await signup(api)
    resp = await api.post(
        "/api/v1/auth/signup",
        json={
            "organization_name": "X",
            "email": unique_email(),
            "password": PASSWORD,
            "full_name": "X",
        },
    )
    assert_throttled(resp, 2)


async def test_guessing_an_invitation_password_is_limited(
    api: AsyncClient, mailbox: Mailbox, org: OrgSetup, monkeypatch: pytest.MonkeyPatch
) -> None:
    existing = await signup(api)
    api.cookies.clear()
    await api.post(
        "/api/v1/org/invitations",
        json={"email": existing["email"], "role": "member"},
        headers=org.admin.headers,
    )
    token = mailbox.token_for(existing["email"])
    limit(monkeypatch, "rate_limit_login_per_ip", "3/minute")
    url = f"/api/v1/org/invitations/{token}/accept"
    assert [
        (await api.post(url, json={"password": f"guess number {i}"})).status_code for i in range(3)
    ] == [401] * 3
    assert_throttled(await api.post(url, json={"password": PASSWORD}), 3)


async def test_authenticated_writes_are_limited_per_user(
    api: AsyncClient, org: OrgSetup, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A brand-new user: the setup helpers above already spent part of the others' budgets.
    fresh = bearer((await signup(api))["access_token"])
    limit(monkeypatch, "rate_limit_write_per_user", "3/minute")
    for i in range(3):
        resp = await api.post("/api/v1/boards", json={"name": f"B{i}"}, headers=fresh)
        assert resp.status_code == 201
        assert resp.headers["x-ratelimit-limit"] == "3"
        assert resp.headers["x-ratelimit-remaining"] == str(2 - i)
    assert_throttled(await api.post("/api/v1/boards", json={"name": "B3"}, headers=fresh), 3)
    # The budget is per user: a colleague is unaffected, and reads are a separate budget.
    mine = await api.post("/api/v1/boards", json={"name": "Mine"}, headers=org.admin.headers)
    assert mine.status_code == 201
    assert (await api.get("/api/v1/boards", headers=fresh)).status_code == 200


async def test_authenticated_reads_are_limited_separately(
    api: AsyncClient, org: OrgSetup, monkeypatch: pytest.MonkeyPatch
) -> None:
    fresh = bearer((await signup(api))["access_token"])
    limit(monkeypatch, "rate_limit_read_per_user", "2/minute")
    first = await api.get("/api/v1/org", headers=fresh)
    second = await api.get("/api/v1/org", headers=fresh)
    assert (first.status_code, second.status_code) == (200, 200)
    assert (first.headers["x-ratelimit-remaining"], second.headers["x-ratelimit-remaining"]) == (
        "1",
        "0",
    )
    assert_throttled(await api.get("/api/v1/org", headers=fresh), 2)
    assert (await api.post("/api/v1/boards", json={"name": "ok"}, headers=fresh)).status_code == 201


async def test_an_invalid_token_is_rejected_before_it_can_consume_anyones_budget(
    api: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    limit(monkeypatch, "rate_limit_read_per_user", "1/minute")
    for _ in range(3):
        assert (
            await api.get("/api/v1/org", headers={"Authorization": "Bearer junk"})
        ).status_code == 401


async def test_a_redis_outage_does_not_take_the_api_down(
    api: AsyncClient, org: OrgSetup, monkeypatch: pytest.MonkeyPatch
) -> None:
    limit(monkeypatch, "rate_limit_login_per_ip", "1/minute")
    limit(monkeypatch, "rate_limit_write_per_user", "1/minute")
    dead = Redis.from_url("redis://127.0.0.1:1/0")
    api._transport.app.dependency_overrides[get_redis_client] = lambda: dead  # type: ignore[attr-defined]
    try:
        for _ in range(3):  # far past either limit, and nothing is throttled
            assert (await login(api, org.admin.email, PASSWORD)).status_code == 200
            made = await api.post(
                "/api/v1/boards", json={"name": "still works"}, headers=org.manager.headers
            )
            assert made.status_code == 201
            assert "x-ratelimit-limit" not in made.headers  # nothing to advertise while degraded
        assert (await api.get("/health")).status_code == 200
    finally:
        await dead.aclose()


async def test_limits_come_from_configuration_not_code(
    api: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    limit(monkeypatch, "rate_limit_login_per_ip", "1/hour")
    await login(api, unique_email())
    blocked = await login(api, unique_email())
    assert blocked.status_code == 429
    assert 3000 < int(blocked.headers["retry-after"]) <= 3600
