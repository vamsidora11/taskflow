import json
import logging
import sys
import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import settings
from app.core.logging import REDACTED, JsonFormatter, RedactingFilter, redact
from app.core.request_context import request_id_var
from tests.helpers import PASSWORD, Mailbox, OrgSetup, bearer, create_org, signup, unique_email

EXPECTED = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "no-referrer",
}


@pytest.fixture
async def org(api: AsyncClient, admin_engine: AsyncEngine) -> OrgSetup:
    return await create_org(api, admin_engine)


# --- security headers ---


async def test_security_headers_are_on_success_and_error_responses(
    api: AsyncClient, org: OrgSetup
) -> None:
    responses = [
        await api.get("/health"),
        await api.get("/api/v1/org", headers=org.admin.headers),  # 200
        await api.get("/api/v1/org"),  # 401
        await api.get("/api/v1/nope", headers=org.admin.headers),  # 404
        await api.post("/api/v1/boards", json={}, headers=org.admin.headers),  # 422
        await api.post(
            "/api/v1/auth/login", json={"email": "x@example.com", "password": "y"}
        ),  # 401
    ]
    for resp in responses:
        for name, value in EXPECTED.items():
            assert resp.headers[name] == value, (resp.url, name)
        assert "geolocation=()" in resp.headers["permissions-policy"]


async def test_api_responses_are_never_cacheable_but_health_is_unaffected(
    api: AsyncClient, org: OrgSetup
) -> None:
    assert (await api.get("/api/v1/org", headers=org.admin.headers)).headers[
        "cache-control"
    ] == "no-store"
    login = await api.post(
        "/api/v1/auth/login", json={"email": org.admin.email, "password": PASSWORD}
    )
    assert login.headers["cache-control"] == "no-store"  # carries an access token
    assert "cache-control" not in (await api.get("/health")).headers


@pytest.mark.parametrize(
    ("env", "hsts"),
    [("development", False), ("ci", False), ("staging", True), ("production", True)],
)
async def test_hsts_is_sent_only_outside_development(
    api: AsyncClient, monkeypatch: pytest.MonkeyPatch, env: str, hsts: bool
) -> None:
    monkeypatch.setattr(settings, "app_env", env)
    resp = await api.get("/health")
    assert ("strict-transport-security" in resp.headers) is hsts
    if hsts:
        assert "max-age=31536000" in resp.headers["strict-transport-security"]


# --- CORS ---


async def test_cors_allows_only_the_configured_frontend_origin(api: AsyncClient) -> None:
    allowed = await api.options(
        "/api/v1/boards",
        headers={
            "Origin": settings.frontend_origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,idempotency-key,content-type",
        },
    )
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == settings.frontend_origin
    assert allowed.headers["access-control-allow-credentials"] == "true"
    assert "idempotency-key" in allowed.headers["access-control-allow-headers"].lower()

    for origin in ("https://evil.example", "http://localhost:9999", "null"):
        denied = await api.options(
            "/api/v1/boards",
            headers={"Origin": origin, "Access-Control-Request-Method": "POST"},
        )
        assert "access-control-allow-origin" not in denied.headers, origin
        assert denied.status_code == 400


async def test_cors_exposes_the_headers_the_frontend_needs(api: AsyncClient) -> None:
    resp = await api.get("/health", headers={"Origin": settings.frontend_origin})
    exposed = resp.headers["access-control-expose-headers"].lower()
    for header in ("x-request-id", "retry-after", "x-ratelimit-remaining", "idempotent-replay"):
        assert header in exposed
    simple = await api.get("/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in simple.headers


async def test_a_429_is_readable_cross_origin(
    api: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "rate_limit_login_per_ip", "1/minute")
    headers = {"Origin": settings.frontend_origin}
    body = {"email": "x@example.com", "password": "y"}
    await api.post("/api/v1/auth/login", json=body, headers=headers)
    blocked = await api.post("/api/v1/auth/login", json=body, headers=headers)
    assert blocked.status_code == 429
    assert blocked.headers["access-control-allow-origin"] == settings.frontend_origin


# --- request ids and error hygiene ---


async def test_error_bodies_never_leak_internals(api: AsyncClient, org: OrgSetup) -> None:
    for resp in (
        await api.get("/api/v1/boards/not-a-uuid", headers=org.admin.headers),
        await api.get("/api/v1/org", headers=bearer("garbage")),
        await api.get(
            "/api/v1/tasks/00000000-0000-0000-0000-000000000000", headers=org.admin.headers
        ),
    ):
        text = resp.text
        assert "Traceback" not in text
        assert "sqlalchemy" not in text.lower()
        assert 'File "' not in text
        assert set(resp.json()["error"]) == {"code", "message", "request_id"}


# --- logging ---


def access_records(caplog: pytest.LogCaptureFixture) -> list[dict[str, Any]]:
    return [r.fields for r in caplog.records if r.name == "taskflow.access"]  # type: ignore[attr-defined]


async def test_each_request_logs_one_structured_line_with_its_request_id(
    api: AsyncClient, org: OrgSetup, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="taskflow.access")
    resp = await api.get("/api/v1/org", headers={**org.member.headers, "X-Request-ID": "trace-77"})
    [entry] = [e for e in access_records(caplog) if e["request_id"] == "trace-77"]
    assert (entry["method"], entry["path"], entry["status"]) == ("GET", "/api/v1/org", 200)
    assert entry["user_id"] == org.member.user_id
    assert entry["duration_ms"] >= 0
    assert resp.headers["x-request-id"] == "trace-77"


async def test_secrets_never_reach_the_logs(
    api: AsyncClient, org: OrgSetup, mailbox: Mailbox, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    session = await signup(api)
    await api.post("/api/v1/auth/login", json={"email": session["email"], "password": PASSWORD})
    await api.get("/api/v1/auth/me", headers=bearer(session["access_token"]))
    invitee = unique_email("inv")
    await api.post(
        "/api/v1/org/invitations",
        json={"email": invitee, "role": "member"},
        headers=org.admin.headers,
    )
    token = mailbox.token_for(invitee)
    await api.post(
        f"/api/v1/org/invitations/{token}/accept", json={"password": PASSWORD, "full_name": "N"}
    )
    await api.get("/api/v1/org", headers=bearer("tampered.token.value"))
    refresh_cookie = api.cookies.get("refresh_token") or ""

    rendered = "\n".join(JsonFormatter().format(r) for r in caplog.records)
    assert rendered  # something was logged
    for secret in (
        PASSWORD,
        session["access_token"],
        token,
        refresh_cookie,
        "tampered.token.value",
    ):
        if secret:
            assert secret not in rendered, f"{secret[:12]}... leaked into the logs"
    assert "Authorization" not in rendered
    paths = [e["path"] for e in access_records(caplog)]
    assert f"/api/v1/org/invitations/{REDACTED}/accept" in paths


# --- redaction unit tests ---


@pytest.mark.parametrize(
    ("raw", "gone"),
    [
        ("Authorization: Bearer abc.def.ghi", "abc.def.ghi"),
        ("sent header bearer SECRETVALUE123", "SECRETVALUE123"),
        ('{"password": "hunter2hunter2", "x": 1}', "hunter2hunter2"),
        ("password=hunter2hunter2&email=a", "hunter2hunter2"),
        ("token: zzzTOKENzzz", "zzzTOKENzzz"),
        ("jwt eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.sig is bad", "eyJhbGciOiJIUzI1NiJ9"),
        ("POST /api/v1/org/invitations/RAWINVITETOKEN/accept 200", "RAWINVITETOKEN"),
    ],
)
def test_redaction_masks_secrets(raw: str, gone: str) -> None:
    assert gone not in redact(raw)


def test_redaction_leaves_ordinary_text_alone() -> None:
    assert redact("created board Roadmap for org 42") == "created board Roadmap for org 42"


def test_the_json_formatter_emits_parseable_lines_with_request_id_and_traceback() -> None:
    token = request_id_var.set("req_abc")
    try:
        try:
            raise ValueError("boom with password=hunter2hunter2")
        except ValueError:
            record = logging.LogRecord(
                "t", logging.ERROR, __file__, 1, "failed", None, sys.exc_info()
            )
        line = JsonFormatter().format(record)
    finally:
        request_id_var.reset(token)
    data = json.loads(line)
    assert (data["level"], data["logger"], data["message"], data["request_id"]) == (
        "ERROR",
        "t",
        "failed",
        "req_abc",
    )
    assert "ValueError" in data["exception"]
    assert "hunter2hunter2" not in line


def test_the_filter_redacts_formatted_messages() -> None:
    record = logging.LogRecord(
        "t", logging.INFO, __file__, 1, "login %s", ("password=abcdefgh1234",), None
    )
    assert RedactingFilter().filter(record)
    assert "abcdefgh1234" not in record.getMessage()
    assert uuid.uuid4()  # keep the import used
