"""HTTP rendering of a freshly issued session: the refresh cookie and the token body."""

from datetime import UTC, datetime

from fastapi import Response

from app.core.config import settings
from app.core.permissions import Role
from app.schemas.auth import TokenResponse
from app.services.auth import AuthTokens

COOKIE_NOTE = (
    "The refresh token is set in an `HttpOnly`, `SameSite=Strict` cookie scoped to "
    "`/api/v1/auth`; it is never returned in the body. Swagger UI sends it automatically "
    "when served from the same origin as the API."
)


def set_refresh_cookie(response: Response, tokens: AuthTokens) -> None:
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


def clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.refresh_cookie_name,
        path=settings.refresh_cookie_path,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
    )


def token_response(tokens: AuthTokens) -> TokenResponse:
    return TokenResponse(
        access_token=tokens.access_token,
        token_type="bearer",
        expires_in=tokens.expires_in,
        organization_id=tokens.organization_id,
        role=Role(tokens.role),
    )
