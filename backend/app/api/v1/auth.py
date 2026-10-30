from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_auth_session, get_client_info, get_current_user, get_tenant_session
from app.core.config import settings
from app.core.permissions import Role
from app.schemas.auth import (
    LoginRequest,
    MeResponse,
    OrganizationSummary,
    SignupRequest,
    SwitchOrganizationRequest,
    TokenResponse,
    UserRead,
)
from app.schemas.errors import ErrorResponse
from app.services.auth import AuthenticatedUser, AuthService, AuthTokens, ClientInfo

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

_COOKIE_NOTE = (
    "The refresh token is set in an `HttpOnly`, `SameSite=Strict` cookie scoped to "
    "`/api/v1/auth`; it is never returned in the body. Swagger UI sends it automatically "
    "when served from the same origin as the API."
)

_RESP_422: dict[int | str, dict[str, Any]] = {
    422: {"model": ErrorResponse, "description": "Request body failed validation"}
}
_RESP_429: dict[int | str, dict[str, Any]] = {
    429: {"model": ErrorResponse, "description": "Rate limit exceeded"}
}
_RESP_401_TOKEN: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "Missing, expired, or invalid access token"}
}


def _set_refresh_cookie(response: Response, tokens: AuthTokens) -> None:
    max_age = int((tokens.refresh_expires_at - datetime.now(UTC)).total_seconds())
    response.set_cookie(
        key=settings.refresh_cookie_name,
        value=tokens.refresh_token,
        max_age=max_age,
        path=settings.refresh_cookie_path,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.refresh_cookie_name,
        path=settings.refresh_cookie_path,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
    )


def _token_response(tokens: AuthTokens) -> TokenResponse:
    return TokenResponse(
        access_token=tokens.access_token,
        token_type="bearer",
        expires_in=tokens.expires_in,
        organization_id=tokens.organization_id,
        role=Role(tokens.role),
    )


@router.post(
    "/signup",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="signup",
    summary="Sign up and create an organization",
    description=(
        "Creates a user, a new organization, and an admin membership, then signs the user in.\n\n"
        "**Roles:** public.\n\n"
        f"{_COOKIE_NOTE}\n\n"
        "**Audit:** `org.created` and `auth.login` entries arrive with the audit log (Phase 5)."
    ),
    responses={
        409: {"model": ErrorResponse, "description": "Email is already registered"},
        **_RESP_422,
        **_RESP_429,
    },
)
async def signup(
    payload: SignupRequest,
    response: Response,
    session: AsyncSession = Depends(get_auth_session),
    client: ClientInfo = Depends(get_client_info),
) -> TokenResponse:
    tokens = await AuthService(session).signup(
        organization_name=payload.organization_name,
        email=payload.email,
        password=payload.password,
        full_name=payload.full_name,
        client=client,
    )
    _set_refresh_cookie(response, tokens)
    return _token_response(tokens)


@router.post(
    "/login",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    operation_id="login",
    summary="Log in with email and password",
    description=(
        "Verifies the credentials and returns an access token for the user's first "
        "organization. Use `POST /api/v1/auth/switch-org` to change organization.\n\n"
        "**Roles:** public.\n\n"
        "An unknown email, a wrong password and a disabled account all return the same "
        "`401 INVALID_CREDENTIALS` response.\n\n"
        f"{_COOKIE_NOTE}"
    ),
    responses={
        401: {"model": ErrorResponse, "description": "Invalid email or password"},
        403: {"model": ErrorResponse, "description": "Account belongs to no organization"},
        **_RESP_422,
        **_RESP_429,
    },
)
async def login(
    payload: LoginRequest,
    response: Response,
    session: AsyncSession = Depends(get_auth_session),
    client: ClientInfo = Depends(get_client_info),
) -> TokenResponse:
    tokens = await AuthService(session).login(
        email=payload.email, password=payload.password, client=client
    )
    _set_refresh_cookie(response, tokens)
    return _token_response(tokens)


@router.post(
    "/refresh",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    operation_id="refresh_token",
    summary="Rotate the refresh token",
    description=(
        "Exchanges the refresh cookie for a new access token and a new refresh cookie. Each "
        "refresh token works once.\n\n"
        "**Roles:** any holder of a valid refresh cookie.\n\n"
        "**Reuse detection:** presenting an already-rotated or revoked token revokes the whole "
        "token family and returns 401, so a stolen token cannot be used silently.\n\n"
        f"{_COOKIE_NOTE}"
    ),
    responses={
        401: {"model": ErrorResponse, "description": "Refresh cookie missing, expired or reused"},
        **_RESP_422,
        **_RESP_429,
    },
)
async def refresh_token(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_auth_session),
    client: ClientInfo = Depends(get_client_info),
) -> TokenResponse:
    tokens = await AuthService(session).refresh(
        refresh_token=request.cookies.get(settings.refresh_cookie_name), client=client
    )
    _set_refresh_cookie(response, tokens)
    return _token_response(tokens)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="logout",
    summary="Log out",
    description=(
        "Revokes the refresh token family of the cookie and clears the cookie. Always returns "
        "204, even when the cookie is missing or unknown.\n\n**Roles:** public."
    ),
    responses={**_RESP_422, **_RESP_429},
)
async def logout(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_auth_session),
) -> None:
    await AuthService(session).logout(
        refresh_token=request.cookies.get(settings.refresh_cookie_name)
    )
    _clear_refresh_cookie(response)


@router.post(
    "/switch-org",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    operation_id="switch_organization",
    summary="Switch the active organization",
    description=(
        "Issues a new access token (and a new refresh cookie) scoped to another organization "
        "the caller belongs to. The previous session's refresh token family is revoked.\n\n"
        "**Roles:** any member of the target organization.\n\n"
        "Returns 404 both when the organization does not exist and when the caller is not a "
        "member, so existence is not revealed.\n\n"
        f"{_COOKIE_NOTE}"
    ),
    responses={
        **_RESP_401_TOKEN,
        404: {"model": ErrorResponse, "description": "Organization not found for this user"},
        **_RESP_422,
        **_RESP_429,
    },
)
async def switch_organization(
    payload: SwitchOrganizationRequest,
    request: Request,
    response: Response,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_auth_session),
    client: ClientInfo = Depends(get_client_info),
) -> TokenResponse:
    tokens = await AuthService(session).switch_organization(
        user_id=user.id,
        target_org_id=payload.organization_id,
        current_refresh_token=request.cookies.get(settings.refresh_cookie_name),
        client=client,
    )
    _set_refresh_cookie(response, tokens)
    return _token_response(tokens)


@router.get(
    "/me",
    response_model=MeResponse,
    status_code=status.HTTP_200_OK,
    operation_id="get_current_account",
    summary="Get the current user and organizations",
    description=(
        "Returns the authenticated user, the organization the token is scoped to, and every "
        "organization the user belongs to.\n\n**Roles:** any authenticated user."
    ),
    responses={**_RESP_401_TOKEN, **_RESP_422, **_RESP_429},
)
async def get_current_account(
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_tenant_session),
) -> MeResponse:
    overview = await AuthService(session).account_overview(user)
    organizations = [
        OrganizationSummary(
            id=o.organization_id,
            name=o.organization_name,
            slug=o.organization_slug,
            role=Role(o.role),
        )
        for o in overview.organizations
    ]
    active = next(o for o in organizations if o.id == user.organization_id)
    return MeResponse(
        user=UserRead(id=user.id, email=user.email, full_name=user.full_name),
        active_organization=active,
        organizations=organizations,
    )
