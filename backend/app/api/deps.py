from collections.abc import AsyncIterator

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import AccessTokenClaims, decode_access_token
from app.core.security_scheme import bearer_scheme
from app.db.session import SessionFactory, get_session_factory, tenant_session
from app.services.auth import AuthenticatedUser, ClientInfo, resolve_authenticated_user

_CURRENT_USER_KEY = "current_user"


def get_factory() -> SessionFactory:
    """Overridable in tests to point the app at a throwaway database."""
    return get_session_factory()


async def get_auth_session(
    factory: SessionFactory = Depends(get_factory),
) -> AsyncIterator[AsyncSession]:
    """Plain session for the auth endpoints, which pick their own tenant context.

    The service commits explicitly; anything left uncommitted is rolled back on close.
    """
    async with factory() as session:
        yield session


def get_client_info(request: Request) -> ClientInfo:
    return ClientInfo(
        user_agent=request.headers.get("user-agent"),
        ip_address=request.client.host if request.client else None,
    )


async def get_token_claims(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> AccessTokenClaims:
    """Validate the bearer token. Depending on `bearer_scheme` is what makes Swagger show the
    lock icon and the Authorize button on every route that uses this chain."""
    return decode_access_token(credentials.credentials)


async def get_tenant_session(
    claims: AccessTokenClaims = Depends(get_token_claims),
    factory: SessionFactory = Depends(get_factory),
) -> AsyncIterator[AsyncSession]:
    """Session scoped to the token's organization for RLS.

    The token is re-verified against the live membership before the route runs, so every
    tenant route is protected even if it never asks for the current user.
    """
    async with tenant_session(factory, claims.org_id, claims.user_id) as session:
        session.info[_CURRENT_USER_KEY] = await resolve_authenticated_user(session, claims)
        yield session


async def get_current_user(
    session: AsyncSession = Depends(get_tenant_session),
) -> AuthenticatedUser:
    user: AuthenticatedUser = session.info[_CURRENT_USER_KEY]
    return user
