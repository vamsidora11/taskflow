import uuid
from collections.abc import AsyncIterator

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session_factory, tenant_session


async def get_active_org_id() -> uuid.UUID:
    """Active organization for the request.

    Phase 2 replaces this with the verified `org_id` claim of the access token, checked
    against the caller's membership. Until then no request can be tenant-scoped.
    """
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")


async def get_tenant_session(
    org_id: uuid.UUID = Depends(get_active_org_id),
) -> AsyncIterator[AsyncSession]:
    async with tenant_session(get_session_factory(), org_id) as session:
        yield session
