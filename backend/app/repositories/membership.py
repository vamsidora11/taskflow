import uuid

from app.db.models.membership import Membership
from app.repositories.base import TenantRepository


class MembershipRepository(TenantRepository[Membership]):
    model = Membership

    async def get_by_user_id(self, user_id: uuid.UUID) -> Membership | None:
        stmt = self.scoped_select().where(Membership.user_id == user_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()
