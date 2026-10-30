import asyncio
import hashlib
import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.api.deps import get_email_sender
from app.services.email import EmailMessage
from tests.helpers import (
    COOKIE,
    PASSWORD,
    Mailbox,
    OrgSetup,
    bearer,
    create_org,
    signup,
    unique_email,
)


@pytest.fixture
async def org(api: AsyncClient, admin_engine: AsyncEngine) -> OrgSetup:
    return await create_org(api, admin_engine)


async def invite(
    api: AsyncClient, org: OrgSetup, email: str, role: str = "member"
) -> dict[str, Any]:
    resp = await api.post(
        "/api/v1/org/invitations", json={"email": email, "role": role}, headers=org.admin.headers
    )
    assert resp.status_code == 201, resp.text
    body: dict[str, Any] = resp.json()
    return body


def accept_url(token: str) -> str:
    return f"/api/v1/org/invitations/{token}/accept"


NEW_ACCOUNT = {"password": PASSWORD, "full_name": "Grace Hopper"}


async def pending_rows(admin_engine: AsyncEngine, org_id: str, email: str) -> int:
    async with admin_engine.connect() as conn:
        return int(
            (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM invitations WHERE organization_id = :o "
                        "AND email = :e AND accepted_at IS NULL"
                    ),
                    {"o": org_id, "e": email.lower()},
                )
            ).scalar_one()
        )


# --- creating invitations --------------------------------------------------------------------


async def test_invite_returns_the_invitation_but_never_the_token(
    api: AsyncClient, mailbox: Mailbox, org: OrgSetup
) -> None:
    email = unique_email("invitee")
    body = await invite(api, org, email, role="manager")
    assert body["email"] == email
    assert body["role"] == "manager"
    assert set(body) == {"id", "email", "role", "expires_at", "created_at"}
    token = mailbox.token_for(email)
    assert token not in str(body)


async def test_invite_emails_a_link_to_the_invitee(
    api: AsyncClient, mailbox: Mailbox, org: OrgSetup
) -> None:
    email = unique_email("invitee")
    await invite(api, org, email)
    [message] = [m for m in mailbox.messages if m.to == email]
    assert "/accept-invite?token=" in message.body
    assert "expires in 7 days" in message.body
    assert org.admin.email not in message.to


async def test_only_the_token_hash_is_stored(
    api: AsyncClient, admin_engine: AsyncEngine, mailbox: Mailbox, org: OrgSetup
) -> None:
    email = unique_email("invitee")
    await invite(api, org, email)
    token = mailbox.token_for(email)
    async with admin_engine.connect() as conn:
        stored = (
            await conn.execute(
                text("SELECT token_hash FROM invitations WHERE email = :e"), {"e": email}
            )
        ).scalar_one()
    assert stored == hashlib.sha256(token.encode()).hexdigest()
    assert token not in stored


async def test_inviting_an_existing_member_is_409(api: AsyncClient, org: OrgSetup) -> None:
    resp = await api.post(
        "/api/v1/org/invitations",
        json={"email": org.member.email, "role": "member"},
        headers=org.admin.headers,
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "ALREADY_MEMBER"


async def test_an_invalid_invite_is_rejected(api: AsyncClient, org: OrgSetup) -> None:
    for payload in ({"email": "not-an-email"}, {"email": unique_email(), "role": "owner"}):
        resp = await api.post("/api/v1/org/invitations", json=payload, headers=org.admin.headers)
        assert resp.status_code == 422


async def test_re_inviting_replaces_the_pending_invitation(
    api: AsyncClient, admin_engine: AsyncEngine, mailbox: Mailbox, org: OrgSetup
) -> None:
    email = unique_email("invitee")
    await invite(api, org, email)
    first = mailbox.token_for(email)
    await invite(api, org, email)
    second = mailbox.token_for(email)
    assert first != second
    assert await pending_rows(admin_engine, org.org_id, email) == 1
    assert (await api.post(accept_url(first), json=NEW_ACCOUNT)).status_code == 404
    assert (await api.post(accept_url(second), json=NEW_ACCOUNT)).status_code == 200


async def test_a_failing_mail_transport_does_not_fail_the_request(
    api: AsyncClient, org: OrgSetup
) -> None:
    class Down:
        async def send(self, message: EmailMessage) -> None:
            raise ConnectionError("smtp down")

    app = api._transport.app  # type: ignore[attr-defined]
    app.dependency_overrides[get_email_sender] = lambda: Down()
    resp = await api.post(
        "/api/v1/org/invitations",
        json={"email": unique_email("invitee"), "role": "member"},
        headers=org.admin.headers,
    )
    assert resp.status_code == 201


# --- accepting: new accounts -----------------------------------------------------------------


async def test_accepting_creates_the_account_membership_and_session(
    api: AsyncClient, mailbox: Mailbox, org: OrgSetup
) -> None:
    email = unique_email("Grace")  # mixed case on purpose
    await invite(api, org, email.upper(), role="manager")
    resp = await api.post(accept_url(mailbox.token_for(email)), json=NEW_ACCOUNT)
    assert resp.status_code == 200
    body = resp.json()
    assert body["organization_id"] == org.org_id
    assert body["role"] == "manager"
    assert COOKIE in api.cookies

    me = await api.get("/api/v1/auth/me", headers=bearer(body["access_token"]))
    assert me.json()["user"]["email"] == email.lower()
    assert me.json()["user"]["full_name"] == "Grace Hopper"
    assert me.json()["active_organization"]["role"] == "manager"

    members = await api.get("/api/v1/org/members", headers=org.admin.headers)
    joined = [m for m in members.json()["items"] if m["email"] == email.lower()]
    assert [m["role"] for m in joined] == ["manager"]

    # The new user can sign in normally afterwards.
    api.cookies.clear()
    login = await api.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200


async def test_an_invitation_is_single_use(
    api: AsyncClient, mailbox: Mailbox, org: OrgSetup
) -> None:
    email = unique_email("invitee")
    await invite(api, org, email)
    token = mailbox.token_for(email)
    assert (await api.post(accept_url(token), json=NEW_ACCOUNT)).status_code == 200
    again = await api.post(accept_url(token), json=NEW_ACCOUNT)
    assert again.status_code == 404
    assert again.json()["error"]["code"] == "INVITATION_NOT_FOUND"


async def test_an_expired_invitation_is_rejected(
    api: AsyncClient, admin_engine: AsyncEngine, mailbox: Mailbox, org: OrgSetup
) -> None:
    email = unique_email("invitee")
    await invite(api, org, email)
    async with admin_engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE invitations SET expires_at = now() - interval '1 second' WHERE email = :e"
            ),
            {"e": email},
        )
    resp = await api.post(accept_url(mailbox.token_for(email)), json=NEW_ACCOUNT)
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "INVITATION_NOT_FOUND"


async def test_unknown_used_and_expired_tokens_are_indistinguishable(
    api: AsyncClient, mailbox: Mailbox, org: OrgSetup
) -> None:
    email = unique_email("invitee")
    await invite(api, org, email)
    token = mailbox.token_for(email)
    await api.post(accept_url(token), json=NEW_ACCOUNT)
    used = await api.post(accept_url(token), json=NEW_ACCOUNT)
    unknown = await api.post(accept_url("x" * 43), json=NEW_ACCOUNT)
    assert used.status_code == unknown.status_code == 404
    a, b = used.json()["error"], unknown.json()["error"]
    assert (a["code"], a["message"]) == (b["code"], b["message"])


async def test_a_new_account_must_give_a_name_and_a_long_password_and_keeps_the_invite(
    api: AsyncClient, mailbox: Mailbox, org: OrgSetup
) -> None:
    email = unique_email("invitee")
    await invite(api, org, email)
    token = mailbox.token_for(email)

    no_name = await api.post(accept_url(token), json={"password": PASSWORD})
    short = await api.post(accept_url(token), json={"password": "short", "full_name": "Grace"})
    for resp in (no_name, short):
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "VALIDATION_ERROR"
    assert '"short"' not in short.text  # the password is never echoed

    # Neither failed attempt consumed the invitation.
    assert (await api.post(accept_url(token), json=NEW_ACCOUNT)).status_code == 200


async def test_accepting_as_admin_grants_admin(
    api: AsyncClient, mailbox: Mailbox, org: OrgSetup
) -> None:
    email = unique_email("invitee")
    await invite(api, org, email, role="admin")
    resp = await api.post(accept_url(mailbox.token_for(email)), json=NEW_ACCOUNT)
    assert resp.json()["role"] == "admin"
    renamed = await api.patch(
        "/api/v1/org", json={"name": "By New Admin"}, headers=bearer(resp.json()["access_token"])
    )
    assert renamed.status_code == 200


# --- accepting: existing accounts ------------------------------------------------------------


async def test_an_existing_account_joins_with_its_password(
    api: AsyncClient, admin_engine: AsyncEngine, mailbox: Mailbox, org: OrgSetup
) -> None:
    existing = await signup(api, org="Their Own Org")
    api.cookies.clear()
    await invite(api, org, existing["email"], role="member")
    token = mailbox.token_for(existing["email"])

    async with admin_engine.connect() as conn:
        users_before = (await conn.execute(text("SELECT count(*) FROM users"))).scalar_one()

    wrong = await api.post(accept_url(token), json={"password": "not the right password"})
    assert wrong.status_code == 401
    assert wrong.json()["error"]["code"] == "INVALID_CREDENTIALS"
    assert COOKIE not in api.cookies

    ok = await api.post(accept_url(token), json={"password": PASSWORD})
    assert ok.status_code == 200
    assert ok.json()["organization_id"] == org.org_id

    me = await api.get("/api/v1/auth/me", headers=bearer(ok.json()["access_token"]))
    assert len(me.json()["organizations"]) == 2  # their own org plus the new one
    async with admin_engine.connect() as conn:
        users_after = (await conn.execute(text("SELECT count(*) FROM users"))).scalar_one()
    assert users_after == users_before  # no duplicate account


async def test_an_existing_account_does_not_need_a_name(
    api: AsyncClient, mailbox: Mailbox, org: OrgSetup
) -> None:
    existing = await signup(api, org="Another Org")
    api.cookies.clear()
    await invite(api, org, existing["email"])
    resp = await api.post(
        accept_url(mailbox.token_for(existing["email"])), json={"password": PASSWORD}
    )
    assert resp.status_code == 200


async def test_possessing_the_link_alone_never_grants_access_to_an_existing_account(
    api: AsyncClient, admin_engine: AsyncEngine, mailbox: Mailbox, org: OrgSetup
) -> None:
    existing = await signup(api, org="Victim Org")
    api.cookies.clear()
    await invite(api, org, existing["email"])
    token = mailbox.token_for(existing["email"])
    attempt = await api.post(
        accept_url(token), json={"password": "attacker guess 123", "full_name": "Eve"}
    )
    assert attempt.status_code == 401
    async with admin_engine.connect() as conn:
        joined = (
            await conn.execute(
                text(
                    "SELECT count(*) FROM memberships m JOIN users u ON u.id = m.user_id "
                    "WHERE u.email = :e AND m.organization_id = :o"
                ),
                {"e": existing["email"], "o": org.org_id},
            )
        ).scalar_one()
    assert joined == 0


async def test_accepting_twice_for_an_existing_member_is_409_and_keeps_nothing_half_done(
    api: AsyncClient, admin_engine: AsyncEngine, mailbox: Mailbox, org: OrgSetup
) -> None:
    existing = await signup(api, org="Dual Org")
    api.cookies.clear()
    await invite(api, org, existing["email"])
    first = mailbox.token_for(existing["email"])
    assert (await api.post(accept_url(first), json={"password": PASSWORD})).status_code == 200

    # They were later re-invited while already a member (e.g. an old email still in flight).
    async with admin_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO invitations (organization_id, email, role, token_hash, expires_at) "
                "VALUES (:o, :e, 'member', :h, now() + interval '1 day')"
            ),
            {
                "o": org.org_id,
                "e": existing["email"],
                "h": hashlib.sha256(b"second-token").hexdigest(),
            },
        )
    resp = await api.post(accept_url("second-token"), json={"password": PASSWORD})
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "ALREADY_MEMBER"
    assert await pending_rows(admin_engine, org.org_id, existing["email"]) == 1  # not consumed


async def test_concurrent_accepts_cannot_both_win(
    api: AsyncClient, mailbox: Mailbox, org: OrgSetup
) -> None:
    email = unique_email("invitee")
    await invite(api, org, email)
    token = mailbox.token_for(email)
    results = await asyncio.gather(
        api.post(accept_url(token), json=NEW_ACCOUNT),
        api.post(accept_url(token), json=NEW_ACCOUNT),
    )
    codes = sorted(r.status_code for r in results)
    assert codes[0] == 200
    assert codes[1] in (404, 409)


async def test_an_invitation_only_adds_to_the_inviting_organization(
    api: AsyncClient, admin_engine: AsyncEngine, mailbox: Mailbox, org: OrgSetup
) -> None:
    other = await create_org(api, admin_engine)
    email = unique_email("invitee")
    await invite(api, org, email)
    resp = await api.post(accept_url(mailbox.token_for(email)), json=NEW_ACCOUNT)
    members = await api.get("/api/v1/org/members", headers=other.admin.headers)
    assert email not in {m["email"] for m in members.json()["items"]}
    assert resp.json()["organization_id"] == org.org_id != other.org_id
    assert uuid.UUID(resp.json()["organization_id"])
