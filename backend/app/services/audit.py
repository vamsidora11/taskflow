"""The single place that writes audit rows (PLAN.md section 8).

Services call `record` inside the transaction of the change it describes, so the row exists if
and only if the change committed. Routers never call it. The request id and client address come
from request context, which is how an audit row is correlated with application logs.
"""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditAction, diff_fields, jsonable
from app.core.exceptions import InvalidCursorError
from app.core.pagination import decode_keyset, encode_keyset
from app.core.request_context import client_ip_var, request_id_var
from app.db.models.audit_log import AuditLog
from app.repositories.audit import AuditFilters, AuditRepository


class AuditService:
    def __init__(self, session: AsyncSession) -> None:
        self.repo = AuditRepository(session)

    async def record(
        self,
        *,
        action: AuditAction,
        entity_type: str,
        organization_id: uuid.UUID | None,
        actor_user_id: uuid.UUID | None,
        entity_id: uuid.UUID | None = None,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Write one row. `before`/`after` become a diff of the changed fields only; `details`
        holds anything else worth keeping. Everything passes through redaction."""
        meta: dict[str, Any] = {}
        if after is not None:
            meta["changes"] = diff_fields(before or {}, after)
        if details:
            meta.update(jsonable(details))
        await self.repo.add(
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            action=action.value,
            entity_type=entity_type,
            entity_id=entity_id,
            meta=meta,
            ip_address=client_ip_var.get(),
            request_id=request_id_var.get(),
        )

    async def list_logs(
        self, organization_id: uuid.UUID, filters: AuditFilters, *, limit: int, cursor: str | None
    ) -> tuple[list[AuditLog], str | None]:
        before_id: int | None = None
        if cursor:
            (raw,) = decode_keyset(cursor, 1)
            if not isinstance(raw, int):
                raise InvalidCursorError()
            before_id = raw
        rows = await self.repo.list_page(
            organization_id, filters, limit=limit + 1, before_id=before_id
        )
        page = rows[:limit]
        next_cursor = encode_keyset(page[-1].id) if len(rows) > limit else None
        return page, next_cursor
