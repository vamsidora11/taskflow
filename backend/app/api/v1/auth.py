from fastapi import APIRouter, Depends, Request, Response, status

from app.api.deps import (
    AuthSession,
    CurrentUser,
    Limiter,
    TenantSession,
    enforce_rate_limit,
    get_client_info,
    ip_rate_limit,
)
from app.api.responses import RATE_LIMITED, UNAUTHORIZED, VALIDATION
from app.api.session_cookie import (
    COOKIE_NOTE,
    clear_refresh_cookie,
    set_refresh_cookie,
    token_response,
)
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
from app.services.auth import AuthService, ClientInfo

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post(
    "/signup",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="signup",
    dependencies=[Depends(ip_rate_limit("signup", "rate_limit_signup_per_ip"))],
    summary="Sign up and create an organization",
    description=(
        "Creates a user, a new organization, and an admin membership, then signs the user in.\n\n"
        "**Roles:** public.\n\n"
        f"{COOKIE_NOTE}\n\n"
        "**Audit:** `org.created` and `auth.login` entries arrive with the audit log (Phase 5)."
    ),
    responses={
        409: {"model": ErrorResponse, "description": "Email is already registered"},
        **VALIDATION,
        **RATE_LIMITED,
    },
)
async def signup(
    payload: SignupRequest,
    response: Response,
    session: AuthSession,
    client: ClientInfo = Depends(get_client_info),
) -> TokenResponse:
    tokens = await AuthService(session).signup(
        organization_name=payload.organization_name,
        email=payload.email,
        password=payload.password,
        full_name=payload.full_name,
        client=client,
    )
    set_refresh_cookie(response, tokens)
    return token_response(tokens)


@router.post(
    "/login",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    operation_id="login",
    dependencies=[Depends(ip_rate_limit("login-ip", "rate_limit_login_per_ip"))],
    summary="Log in with email and password",
    description=(
        "Verifies the credentials and returns an access token for the user's first "
        "organization. Use `POST /api/v1/auth/switch-org` to change organization.\n\n"
        "**Roles:** public.\n\n"
        "An unknown email, a wrong password and a disabled account all return the same "
        "`401 INVALID_CREDENTIALS` response.\n\n"
        f"{COOKIE_NOTE}"
    ),
    responses={
        401: {"model": ErrorResponse, "description": "Invalid email or password"},
        403: {"model": ErrorResponse, "description": "Account belongs to no organization"},
        **VALIDATION,
        **RATE_LIMITED,
    },
)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    session: AuthSession,
    limiter: Limiter,
    client: ClientInfo = Depends(get_client_info),
) -> TokenResponse:
    # Per account as well as per IP, so a botnet cannot spread guesses at one victim.
    await enforce_rate_limit(
        limiter, request, "login-email", payload.email.lower(), settings.rate_limit_login_per_email
    )
    tokens = await AuthService(session).login(
        email=payload.email, password=payload.password, client=client
    )
    set_refresh_cookie(response, tokens)
    return token_response(tokens)


@router.post(
    "/refresh",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    operation_id="refresh_token",
    dependencies=[Depends(ip_rate_limit("refresh-ip", "rate_limit_refresh_per_ip"))],
    summary="Rotate the refresh token",
    description=(
        "Exchanges the refresh cookie for a new access token and a new refresh cookie. Each "
        "refresh token works once.\n\n"
        "**Roles:** any holder of a valid refresh cookie.\n\n"
        "**Reuse detection:** presenting an already-rotated or revoked token revokes the whole "
        "token family and returns 401, so a stolen token cannot be used silently.\n\n"
        f"{COOKIE_NOTE}"
    ),
    responses={
        401: {"model": ErrorResponse, "description": "Refresh cookie missing, expired or reused"},
        **VALIDATION,
        **RATE_LIMITED,
    },
)
async def refresh_token(
    request: Request,
    response: Response,
    session: AuthSession,
    client: ClientInfo = Depends(get_client_info),
) -> TokenResponse:
    tokens = await AuthService(session).refresh(
        refresh_token=request.cookies.get(settings.refresh_cookie_name), client=client
    )
    set_refresh_cookie(response, tokens)
    return token_response(tokens)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="logout",
    summary="Log out",
    description=(
        "Revokes the refresh token family of the cookie and clears the cookie. Always returns "
        "204, even when the cookie is missing or unknown.\n\n**Roles:** public."
    ),
    responses={**VALIDATION, **RATE_LIMITED},
)
async def logout(
    request: Request,
    response: Response,
    session: AuthSession,
) -> None:
    await AuthService(session).logout(
        refresh_token=request.cookies.get(settings.refresh_cookie_name)
    )
    clear_refresh_cookie(response)


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
        f"{COOKIE_NOTE}"
    ),
    responses={
        **UNAUTHORIZED,
        404: {"model": ErrorResponse, "description": "Organization not found for this user"},
        **VALIDATION,
        **RATE_LIMITED,
    },
)
async def switch_organization(
    payload: SwitchOrganizationRequest,
    request: Request,
    response: Response,
    user: CurrentUser,
    session: AuthSession,
    client: ClientInfo = Depends(get_client_info),
) -> TokenResponse:
    tokens = await AuthService(session).switch_organization(
        user_id=user.id,
        target_org_id=payload.organization_id,
        current_refresh_token=request.cookies.get(settings.refresh_cookie_name),
        client=client,
    )
    set_refresh_cookie(response, tokens)
    return token_response(tokens)


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
    responses={**UNAUTHORIZED, **VALIDATION, **RATE_LIMITED},
)
async def get_current_account(
    user: CurrentUser,
    session: TenantSession,
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
