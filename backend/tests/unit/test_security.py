import re
import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from pydantic import ValidationError

from app.core.config import DEFAULT_JWT_SECRET, Settings, settings
from app.core.exceptions import InvalidTokenError
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    hash_refresh_token,
    new_refresh_token,
    verify_password,
)
from app.services.auth import slugify

USER_ID = uuid.uuid4()
ORG_ID = uuid.uuid4()


def _forge(**overrides: object) -> str:
    now = datetime.now(UTC)
    payload: dict[str, object] = {
        "sub": str(USER_ID),
        "org_id": str(ORG_ID),
        "role": "admin",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=5)).timestamp()),
        "jti": "abc",
        "type": "access",
    }
    payload.update(overrides)
    payload = {k: v for k, v in payload.items() if v is not None}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def test_password_hash_is_argon2id_and_verifies() -> None:
    hashed = hash_password("correct horse battery staple")
    assert hashed.startswith("$argon2id$")
    assert verify_password("correct horse battery staple", hashed)
    assert not verify_password("wrong password entirely", hashed)


def test_hashing_is_salted() -> None:
    assert hash_password("same password 123") != hash_password("same password 123")


def test_verify_rejects_a_malformed_hash_instead_of_raising() -> None:
    assert verify_password("anything", "not-a-hash") is False


def test_access_token_round_trip() -> None:
    token, expires_in = create_access_token(USER_ID, ORG_ID, "manager")
    claims = decode_access_token(token)
    assert (claims.user_id, claims.org_id, claims.role) == (USER_ID, ORG_ID, "manager")
    assert expires_in == settings.access_token_ttl_minutes * 60
    raw = jwt.decode(token, options={"verify_signature": False})
    assert set(raw) == {"sub", "org_id", "role", "iat", "exp", "jti", "type"}
    assert raw["type"] == "access"
    assert raw["exp"] - raw["iat"] == expires_in


def test_access_token_ids_are_unique() -> None:
    a, _ = create_access_token(USER_ID, ORG_ID, "admin")
    b, _ = create_access_token(USER_ID, ORG_ID, "admin")
    assert decode_access_token(a).jti != decode_access_token(b).jti


@pytest.mark.parametrize(
    "token",
    [
        pytest.param(
            _forge(exp=int((datetime.now(UTC) - timedelta(minutes=1)).timestamp())), id="expired"
        ),
        pytest.param(_forge(type="refresh"), id="wrong-type"),
        pytest.param(_forge(sub="not-a-uuid"), id="bad-sub"),
        pytest.param(_forge(org_id=None), id="missing-org"),
        pytest.param(_forge(exp=None), id="missing-exp"),
        pytest.param(
            jwt.encode(
                {"sub": str(USER_ID)}, "some-other-secret-key-of-32-bytes-or-more!!", "HS256"
            ),
            id="wrong-secret",
        ),
        pytest.param(
            jwt.encode({"sub": str(USER_ID), "type": "access"}, key=None, algorithm="none"),
            id="alg-none",
        ),
        pytest.param("garbage", id="not-a-jwt"),
        pytest.param("", id="empty"),
    ],
)
def test_invalid_access_tokens_are_rejected(token: str) -> None:
    with pytest.raises(InvalidTokenError):
        decode_access_token(token)


def test_tampered_payload_is_rejected() -> None:
    token, _ = create_access_token(USER_ID, ORG_ID, "member")
    header, _payload, signature = token.split(".")
    forged = jwt.utils.base64url_encode(b'{"sub":"x","org_id":"y","role":"admin"}').decode()
    with pytest.raises(InvalidTokenError):
        decode_access_token(f"{header}.{forged}.{signature}")


def test_refresh_tokens_are_random_and_hashed_deterministically() -> None:
    a, b = new_refresh_token(), new_refresh_token()
    assert a != b
    assert len(a) >= 43  # at least 32 bytes of entropy, url-safe encoded
    assert re.fullmatch(r"[0-9a-f]{64}", hash_refresh_token(a))
    assert hash_refresh_token(a) == hash_refresh_token(a)
    assert hash_refresh_token(a) != hash_refresh_token(b)
    assert a not in hash_refresh_token(a)


def test_slugify() -> None:
    assert re.fullmatch(r"acme-inc-[0-9a-f]{6}", slugify("  Acme, Inc! "))
    assert re.fullmatch(r"org-[0-9a-f]{6}", slugify("!!!"))


def test_production_refuses_the_default_jwt_secret() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, app_env="production", jwt_secret_key=DEFAULT_JWT_SECRET)
    Settings(_env_file=None, app_env="production", jwt_secret_key="x" * 40)
