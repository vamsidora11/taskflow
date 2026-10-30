import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.organization import Organization


class OrganizationRepository:
    """RLS limits organizations to the session's active one."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, org_id: uuid.UUID) -> Organization | None:
        return (
            await self.session.execute(select(Organization).where(Organization.id == org_id))
        ).scalar_one_or_none()

    async def add(self, *, org_id: uuid.UUID, name: str, slug: str) -> Organization:
        org = Organization(id=org_id, name=name, slug=slug)
        self.session.add(org)
        await self.session.flush()
        return org
