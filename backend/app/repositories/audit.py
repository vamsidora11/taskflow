import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import bindparam, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.audit_log import AuditLog

_INSERT = text(
    "INSERT INTO audit_logs (organization_id, actor_user_id, action, entity_type, entity_id, "
    "metadata, ip_address, request_id) VALUES (:organization_id, :actor_user_id, :action, "
    ":entity_type, :entity_id, :meta, :ip_address, :request_id)"
).bindparams(bindparam("meta", type_=JSONB))


@dataclass(frozen=True)
class AuditFilters:
    action: str | None = None
    entity_type: str | None = None
    actor_user_id: uuid.UUID | None = None
    created_from: datetime | None = None
    created_to: datetime | None = None


class AuditRepository:
    """Insert and read only. There is intentionally no update or delete method, and the
    database role has no privilege for them either."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(
        self,
        *,
        organization_id: uuid.UUID | None,
        actor_user_id: uuid.UUID | None,
        action: str,
        entity_type: str,
        entity_id: uuid.UUID | None,
        meta: dict[str, Any],
        ip_address: str | None,
        request_id: str | None,
    ) -> None:
        # Explicit SQL, not the ORM or a Core insert: both fetch the new identity key with
        # RETURNING, and Postgres checks RETURNING rows against the SELECT policy. Tenant-less
        # system rows are deliberately invisible to that policy, so the insert must return nothing.
        await self.session.execute(
            _INSERT,
            {
                "organization_id": organization_id,
                "actor_user_id": actor_user_id,
                "action": action,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "meta": meta,
                "ip_address": ip_address,
                "request_id": request_id,
            },
        )

    async def list_page(
        self,
        organization_id: uuid.UUID,
        filters: AuditFilters,
        *,
        limit: int,
        before_id: int | None,
    ) -> list[AuditLog]:
        """Newest first, keyset-paginated on the monotonic id."""
        stmt = (
            select(AuditLog)
            .where(AuditLog.organization_id == organization_id)
            .order_by(AuditLog.id.desc())
            .limit(limit)
        )
        if filters.action:
            stmt = stmt.where(AuditLog.action == filters.action)
        if filters.entity_type:
            stmt = stmt.where(AuditLog.entity_type == filters.entity_type)
        if filters.actor_user_id:
            stmt = stmt.where(AuditLog.actor_user_id == filters.actor_user_id)
        if filters.created_from:
            stmt = stmt.where(AuditLog.created_at >= filters.created_from)
        if filters.created_to:
            stmt = stmt.where(AuditLog.created_at <= filters.created_to)
        if before_id is not None:
            stmt = stmt.where(AuditLog.id < before_id)
        return list((await self.session.execute(stmt)).scalars().all())
