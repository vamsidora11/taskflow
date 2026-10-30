from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import PermissionDeniedError
from app.core.permissions import Permission, has_permission
from app.core.security import AccessTokenClaims, decode_access_token
from app.core.security_scheme import bearer_scheme
from app.db.redis import get_redis
from app.db.session import SessionFactory, get_session_factory, tenant_session
from app.services.auth import AuthenticatedUser, ClientInfo, resolve_authenticated_user
from app.services.email import EmailSender, build_email_sender
from app.services.idempotency import (
    IdempotencyStore,
    IdempotentReplay,
    StoredResponse,
    fingerprint,
)

_CURRENT_USER_KEY = "current_user"


def get_factory() -> SessionFactory:
    """Overridable in tests to point the app at a throwaway database."""
    return get_session_factory()


def get_email_sender() -> EmailSender:
    """Overridable in tests to capture outgoing mail."""
    return build_email_sender()


EmailSenderDep = Annotated[EmailSender, Depends(get_email_sender)]


async def get_auth_session(
    factory: SessionFactory = Depends(get_factory),
) -> AsyncIterator[AsyncSession]:
    """Plain session for the auth endpoints, which pick their own tenant context.

    The service commits explicitly; anything left uncommitted is rolled back on close.
    """
    async with factory() as session:
        yield session


AuthSession = Annotated[AsyncSession, Depends(get_auth_session, scope="function")]


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
    tenant route is protected even if it never asks for the current user. The transaction
    commits (or rolls back) when the route returns.
    """
    async with tenant_session(factory, claims.org_id, claims.user_id) as session:
        session.info[_CURRENT_USER_KEY] = await resolve_authenticated_user(session, claims)
        yield session


# `scope="function"` makes FastAPI run this dependency's cleanup, and therefore the COMMIT, before
# the response is sent. With the default scope the commit would run afterwards: a client could
# read its 201 before the write is durable, and a failed commit would never reach it. Every use
# must pass the same scope, or FastAPI would open a second session for the same request.
TenantSession = Annotated[AsyncSession, Depends(get_tenant_session, scope="function")]


async def get_current_user(session: TenantSession) -> AuthenticatedUser:
    user: AuthenticatedUser = session.info[_CURRENT_USER_KEY]
    return user


CurrentUser = Annotated[AuthenticatedUser, Depends(get_current_user)]


def require_permission(
    permission: Permission,
) -> Callable[[AuthenticatedUser], Awaitable[AuthenticatedUser]]:
    """Dependency factory: 403 unless the caller's role in the active organization has the
    permission. Returns the user, so routes can both guard and use it:

        user: AuthenticatedUser = Depends(require_permission(Permission.TASK_DELETE))
    """

    async def checker(user: CurrentUser) -> AuthenticatedUser:
        if not has_permission(user.role, permission):
            raise PermissionDeniedError()
        return user

    return checker


def get_redis_client() -> Redis:
    """Overridable in tests to use an in-memory or throwaway Redis."""
    return get_redis()


def get_idempotency_store(redis: Redis = Depends(get_redis_client)) -> IdempotencyStore:
    return IdempotencyStore(redis)


@dataclass
class IdempotencyContext:
    """Handed to the route, which records the response it is about to return."""

    result: StoredResponse | None = None


async def idempotency_guard(
    request: Request,
    claims: AccessTokenClaims = Depends(get_token_claims),
    store: IdempotencyStore = Depends(get_idempotency_store),
    idempotency_key: str | None = Header(
        default=None,
        alias="Idempotency-Key",
        min_length=1,
        max_length=128,
        description=(
            "Unique key (max 128 chars) that makes retries safe: repeating the request within "
            "24 hours returns the original response instead of creating a duplicate."
        ),
        examples=["6f1c2a8e-4b7d-4e9a-9d1f-2b3c4d5e6f70"],
    ),
) -> AsyncIterator[IdempotencyContext | None]:
    """Replay-or-run guard for POST routes that accept an `Idempotency-Key`.

    Declare it BEFORE the session dependencies in a route's signature. Dependencies are torn
    down in reverse order, so the stored response is written only after the tenant session has
    committed: a failed commit releases the key instead of recording a response for nothing.
    """
    if idempotency_key is None:
        yield None
        return
    scope = f"{claims.org_id}:{claims.user_id}"
    request_fingerprint = fingerprint(await request.body(), request.method, request.url.path)
    request_key = f"{request.url.path}:{idempotency_key}"
    replay = await store.begin(scope, request_key, request_fingerprint)
    if replay is not None:
        raise IdempotentReplay(replay)
    context = IdempotencyContext()
    try:
        yield context
    except BaseException:
        await store.abort(scope, request_key)
        raise
    if context.result is not None:
        await store.complete(scope, request_key, request_fingerprint, context.result)
    else:
        await store.abort(scope, request_key)


IdempotencyGuard = Annotated[
    IdempotencyContext | None, Depends(idempotency_guard, scope="function")
]
