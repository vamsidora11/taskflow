"""Organization settings and member management.

Permission checks happen at the router (`require_permission`); the rules here are the ones that
depend on data, such as never leaving an organization without an admin. Audit hooks
(org.updated, member.role_changed, member.removed) arrive with AuditService in Phase 5.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import LastAdminError, MemberNotFoundError, OrganizationNotFoundError
from app.core.pagination import decode_cursor, encode_cursor
from app.core.permissions import Role
from app.db.models.organization import Organization
from app.repositories.membership import MemberRow, MembershipRepository
from app.repositories.organization import OrganizationRepository
from app.repositories.refresh_token import RefreshTokenRepository
from app.repositories.user import UserRepository
from app.services.auth import AuthenticatedUser


class OrganizationService:
    def __init__(self, session: AsyncSession, actor: AuthenticatedUser) -> None:
        self.session = session
        self.org_id = actor.organization_id
        self.orgs = OrganizationRepository(session)
        self.members = MembershipRepository(session, actor.organization_id)

    async def get(self) -> Organization:
        org = await self.orgs.get(self.org_id)
        if org is None:
            raise OrganizationNotFoundError()
        return org

    async def update(self, *, name: str | None) -> Organization:
        org = await self.get()
        if name is not None and name != org.name:
            org.name = name
            await self.session.flush()
            await self.session.refresh(org)  # pick up the database-set updated_at
        return org

    async def list_members(
        self, *, limit: int, cursor: str | None
    ) -> tuple[list[MemberRow], str | None]:
        after = decode_cursor(cursor) if cursor else None
        rows = await self.members.list_members(limit=limit + 1, after=after)
        page = rows[:limit]
        next_cursor = encode_cursor(page[-1].joined_at, page[-1].id) if len(rows) > limit else None
        return page, next_cursor

    async def change_role(self, *, user_id: uuid.UUID, role: Role) -> MemberRow:
        admins = await self.members.lock_admins()
        membership = await self.members.get_by_user_id(user_id)
        if membership is None:
            raise MemberNotFoundError()
        if membership.role == Role.ADMIN and role != Role.ADMIN and admins == [user_id]:
            raise LastAdminError()
        membership.role = role.value
        await self.session.flush()
        return await self._member_row(membership.id, user_id, role.value, membership.created_at)

    async def remove_member(self, *, user_id: uuid.UUID) -> None:
        admins = await self.members.lock_admins()
        membership = await self.members.get_by_user_id(user_id)
        if membership is None:
            raise MemberNotFoundError()
        if membership.role == Role.ADMIN and admins == [user_id]:
            raise LastAdminError()
        await self.members.delete(membership)
        # Their access tokens already fail the per-request membership check; ending the refresh
        # sessions too means they cannot mint new ones for this organization either.
        await RefreshTokenRepository(self.session).revoke_for_user_in_org(
            user_id, self.org_id, datetime.now(UTC)
        )

    async def _member_row(
        self, membership_id: uuid.UUID, user_id: uuid.UUID, role: str, joined_at: datetime
    ) -> MemberRow:
        user = await UserRepository(self.session).get(user_id)
        if user is None:  # pragma: no cover - a membership always references a visible user
            raise MemberNotFoundError()
        return MemberRow(
            id=membership_id,
            user_id=user_id,
            email=user.email,
            full_name=user.full_name,
            role=role,
            joined_at=joined_at,
        )
