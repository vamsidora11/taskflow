import uuid
from collections.abc import Sequence
from typing import Any, Protocol

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession


class TenantModel(Protocol):
    """Shape shared by every tenant-owned ORM model (see `TenantMixin`)."""

    id: Any
    organization_id: Any
    created_at: Any

    def __init__(self, **kwargs: Any) -> None: ...


class TenantRepository[ModelT: TenantModel]:
    """Base for repositories of tenant-owned tables.

    Every query is filtered by `organization_id` in addition to the database's RLS policy,
    so a missing `app.current_org_id` setting still cannot widen results.
    """

    model: type[ModelT]

    def __init__(self, session: AsyncSession, organization_id: uuid.UUID) -> None:
        self.session = session
        self.organization_id = organization_id

    def scoped_select(self) -> Select[ModelT]:
        return select(self.model).where(self.model.organization_id == self.organization_id)

    async def get(self, entity_id: uuid.UUID) -> ModelT | None:
        stmt = self.scoped_select().where(self.model.id == entity_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list(self, *, limit: int = 100, offset: int = 0) -> Sequence[ModelT]:
        stmt = self.scoped_select().order_by(self.model.created_at).limit(limit).offset(offset)
        return (await self.session.execute(stmt)).scalars().all()

    async def add(self, **values: Any) -> ModelT:
        entity = self.model(organization_id=self.organization_id, **values)
        self.session.add(entity)
        await self.session.flush()
        return entity
