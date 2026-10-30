import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select, tuple_

from app.core.permissions import Role
from app.db.models.membership import Membership
from app.db.models.user import User
from app.repositories.base import TenantRepository


@dataclass(frozen=True)
class MemberRow:
    id: uuid.UUID  # membership id, the keyset tiebreaker
    user_id: uuid.UUID
    email: str
    full_name: str
    role: str
    joined_at: datetime


class MembershipRepository(TenantRepository[Membership]):
    model = Membership

    async def get_by_user_id(self, user_id: uuid.UUID) -> Membership | None:
        stmt = self.scoped_select().where(Membership.user_id == user_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_members(
        self, *, limit: int, after: tuple[datetime, uuid.UUID] | None = None
    ) -> list[MemberRow]:
        """Members with their profile, oldest first. Fetches `limit` rows after the cursor."""
        stmt = (
            select(
                Membership.id,
                Membership.user_id,
                User.email,
                User.full_name,
                Membership.role,
                Membership.created_at,
            )
            .join(User, User.id == Membership.user_id)
            .where(Membership.organization_id == self.organization_id)
            .order_by(Membership.created_at, Membership.id)
            .limit(limit)
        )
        if after is not None:
            stmt = stmt.where(tuple_(Membership.created_at, Membership.id) > tuple_(*after))
        return [
            MemberRow(
                id=r.id,
                user_id=r.user_id,
                email=r.email,
                full_name=r.full_name,
                role=r.role,
                joined_at=r.created_at,
            )
            for r in await self.session.execute(stmt)
        ]

    async def lock_admins(self) -> list[uuid.UUID]:
        """Row-lock every admin membership of the organization and return their user ids.

        Concurrent role changes or removals queue up behind this lock, so two admins demoting
        each other at the same instant cannot both pass the last-admin check.
        """
        stmt = (
            select(Membership.user_id)
            .where(
                Membership.organization_id == self.organization_id,
                Membership.role == Role.ADMIN.value,
            )
            .order_by(Membership.id)
            .with_for_update()
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def delete(self, membership: Membership) -> None:
        await self.session.delete(membership)
        await self.session.flush()
