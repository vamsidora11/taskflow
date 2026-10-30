"""Shared helpers for API tests."""

import re
import uuid
from dataclasses import dataclass
from typing import Any

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import settings
from app.services.email import EmailMessage

PASSWORD = "correct horse battery staple"
COOKIE = settings.refresh_cookie_name


def unique_email(prefix: str = "user") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


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


class Mailbox:
    """Captures outgoing mail instead of sending it."""

    def __init__(self) -> None:
        self.messages: list[EmailMessage] = []

    async def send(self, message: EmailMessage) -> None:
        self.messages.append(message)

    def token_for(self, email: str) -> str:
        """The invitation token from the newest message sent to `email`."""
        for message in reversed(self.messages):
            if message.to == email.lower():
                match = re.search(r"token=([A-Za-z0-9_-]+)", message.body)
                assert match, message.body
                return match.group(1)
        raise AssertionError(f"no mail sent to {email}")


@dataclass(frozen=True)
class Actor:
    """A signed-in user acting inside a particular organization."""

    token: str
    user_id: str
    email: str
    role: str

    @property
    def headers(self) -> dict[str, str]:
        return bearer(self.token)


async def add_member(api: AsyncClient, admin_engine: AsyncEngine, org_id: str, role: str) -> Actor:
    """Create a user with its own organization, add it to `org_id` with `role`, and sign it in
    to `org_id`. Membership is inserted directly so these tests do not depend on invitations."""
    home = await signup(api, org=f"Home {uuid.uuid4().hex[:6]}")
    me = await api.get("/api/v1/auth/me", headers=bearer(home["access_token"]))
    user_id = me.json()["user"]["id"]
    async with admin_engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO memberships (organization_id, user_id, role) VALUES (:o, :u, :r)"),
            {"o": org_id, "u": user_id, "r": role},
        )
    switched = await api.post(
        "/api/v1/auth/switch-org",
        json={"organization_id": org_id},
        headers=bearer(home["access_token"]),
    )
    assert switched.status_code == 200, switched.text
    api.cookies.clear()
    return Actor(
        token=switched.json()["access_token"], user_id=user_id, email=home["email"], role=role
    )


@dataclass(frozen=True)
class OrgSetup:
    org_id: str
    admin: Actor
    manager: Actor
    member: Actor

    def actor(self, role: str) -> Actor:
        return {"admin": self.admin, "manager": self.manager, "member": self.member}[role]


async def create_org(api: AsyncClient, admin_engine: AsyncEngine) -> OrgSetup:
    """A fresh organization with one signed-in actor per role."""
    founder = await signup(api, org=f"Org {uuid.uuid4().hex[:6]}")
    org_id = founder["organization_id"]
    me = await api.get("/api/v1/auth/me", headers=bearer(founder["access_token"]))
    api.cookies.clear()
    admin = Actor(
        token=founder["access_token"],
        user_id=me.json()["user"]["id"],
        email=founder["email"],
        role="admin",
    )
    manager = await add_member(api, admin_engine, org_id, "manager")
    member = await add_member(api, admin_engine, org_id, "member")
    return OrgSetup(org_id=org_id, admin=admin, manager=manager, member=member)
