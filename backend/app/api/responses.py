"""Shared OpenAPI `responses` fragments so every route documents its errors the same way."""

from typing import Any

from app.schemas.errors import ErrorResponse

ResponseSpec = dict[int | str, dict[str, Any]]


def error(status: int, description: str) -> ResponseSpec:
    return {status: {"model": ErrorResponse, "description": description}}


UNAUTHORIZED = error(401, "Missing, expired, or invalid access token")
FORBIDDEN = error(403, "Caller's role lacks the required permission")
VALIDATION = error(422, "Request failed validation")
RATE_LIMITED = error(429, "Rate limit exceeded")
