"""Password hashing, access-token JWTs and refresh-token helpers. No FastAPI imports."""

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.config import settings
from app.core.exceptions import InvalidTokenError

MIN_PASSWORD_LENGTH = 12

_hasher = PasswordHasher()  # Argon2id with the library's current recommended parameters
# Verified against when the email is unknown, so login timing does not reveal which emails exist.
DUMMY_PASSWORD_HASH = _hasher.hash("not-a-real-password-for-timing-equalisation")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


@dataclass(frozen=True)
class AccessTokenClaims:
    user_id: uuid.UUID
    org_id: uuid.UUID
    role: str
    jti: str
    expires_at: datetime


def create_access_token(user_id: uuid.UUID, org_id: uuid.UUID, role: str) -> tuple[str, int]:
    """Return the signed JWT and its lifetime in seconds."""
    now = datetime.now(UTC)
    lifetime = timedelta(minutes=settings.access_token_ttl_minutes)
    payload = {
        "sub": str(user_id),
        "org_id": str(org_id),
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + lifetime).timestamp()),
        "jti": uuid.uuid4().hex,
        "type": "access",
    }
    token = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    return token, int(lifetime.total_seconds())


def decode_access_token(token: str) -> AccessTokenClaims:
    """Validate signature, expiry and shape. Every failure raises the same generic error."""
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["sub", "org_id", "role", "iat", "exp", "jti", "type"]},
        )
        if payload["type"] != "access":
            raise InvalidTokenError()
        return AccessTokenClaims(
            user_id=uuid.UUID(payload["sub"]),
            org_id=uuid.UUID(payload["org_id"]),
            role=str(payload["role"]),
            jti=str(payload["jti"]),
            expires_at=datetime.fromtimestamp(payload["exp"], tz=UTC),
        )
    except (jwt.PyJWTError, ValueError, KeyError, TypeError) as exc:
        raise InvalidTokenError() from exc


def new_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_token(token: str) -> str:
    """SHA-256 is enough here: the input is 256+ bits of randomness, not a guessable password."""
    return hashlib.sha256(token.encode()).hexdigest()


hash_refresh_token = hash_token
