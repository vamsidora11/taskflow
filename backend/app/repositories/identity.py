import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class UserRecord:
    id: uuid.UUID
    email: str
    password_hash: str
    full_name: str
    is_active: bool


@dataclass(frozen=True)
class OrganizationMembershipRecord:
    organization_id: uuid.UUID
    organization_name: str
    organization_slug: str
    role: str


@dataclass(frozen=True)
class InvitationRecord:
    id: uuid.UUID
    organization_id: uuid.UUID
    email: str
    role: str
    expires_at: datetime
    accepted_at: datetime | None


class IdentityRepository:
    """Cross-tenant lookups that must work before an organization is chosen.

    They go through SECURITY DEFINER functions (see migration 0002) rather than widening any
    RLS policy: one finds an account by email, the other lists the memberships of the user in
    `app.current_user_id` only.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def find_user_by_email(self, email: str) -> UserRecord | None:
        result = await self.session.execute(
            text("SELECT * FROM auth_find_user_by_email(:email)"), {"email": email}
        )
        row = result.one_or_none()
        if row is None:
            return None
        return UserRecord(
            id=row.id,
            email=row.email,
            password_hash=row.password_hash,
            full_name=row.full_name,
            is_active=row.is_active,
        )

    async def find_invitation(self, token_hash: str) -> InvitationRecord | None:
        result = await self.session.execute(
            text("SELECT * FROM auth_find_invitation(:h)"), {"h": token_hash}
        )
        row = result.one_or_none()
        if row is None:
            return None
        return InvitationRecord(
            id=row.id,
            organization_id=row.organization_id,
            email=row.email,
            role=row.role,
            expires_at=row.expires_at,
            accepted_at=row.accepted_at,
        )

    async def list_memberships(self) -> list[OrganizationMembershipRecord]:
        result = await self.session.execute(text("SELECT * FROM auth_list_memberships()"))
        return [
            OrganizationMembershipRecord(
                organization_id=r.organization_id,
                organization_name=r.organization_name,
                organization_slug=r.organization_slug,
                role=r.role,
            )
            for r in result
        ]
