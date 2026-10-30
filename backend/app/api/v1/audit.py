import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import TenantSession, require_permission
from app.api.responses import FORBIDDEN, RATE_LIMITED, UNAUTHORIZED, VALIDATION
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from app.core.permissions import Permission
from app.repositories.audit import AuditFilters
from app.schemas.audit import AuditLogRead
from app.schemas.common import Page
from app.services.audit import AuditService
from app.services.auth import AuthenticatedUser

router = APIRouter(prefix="/api/v1", tags=["audit"])


@router.get(
    "/audit-logs",
    response_model=Page[AuditLogRead],
    status_code=status.HTTP_200_OK,
    operation_id="list_audit_logs",
    summary="List the activity log",
    description=(
        "The organization's append-only audit trail, newest first, with cursor pagination. "
        "Filters combine with AND.\n\n**Roles:** Admin, Manager."
    ),
    responses={**UNAUTHORIZED, **FORBIDDEN, **VALIDATION, **RATE_LIMITED},
)
async def list_audit_logs(
    session: TenantSession,
    user: AuthenticatedUser = Depends(require_permission(Permission.AUDIT_VIEW)),
    action: str | None = Query(None, max_length=64, description="Exact action, e.g. `task.moved`."),
    entity_type: str | None = Query(None, max_length=32, description="e.g. `task`, `member`."),
    actor_user_id: uuid.UUID | None = Query(None, description="Only entries by this user."),
    created_from: datetime | None = Query(None, description="Entries at or after this time."),
    created_to: datetime | None = Query(None, description="Entries at or before this time."),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT, description="Page size."),
    cursor: str | None = Query(None, max_length=200, description="`next_cursor` of the last page."),
) -> Page[AuditLogRead]:
    rows, next_cursor = await AuditService(session).list_logs(
        user.organization_id,
        AuditFilters(
            action=action,
            entity_type=entity_type,
            actor_user_id=actor_user_id,
            created_from=created_from,
            created_to=created_to,
        ),
        limit=limit,
        cursor=cursor,
    )
    return Page[AuditLogRead](
        items=[AuditLogRead.from_log(r) for r in rows], next_cursor=next_cursor
    )
