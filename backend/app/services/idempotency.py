"""Idempotency-Key support (PLAN.md section 10): retrying a POST with the same key returns the
original response instead of creating a duplicate.

State lives in Redis for 24 hours. Per key, atomically:
  absent    -> claim it as "pending" (SET NX) and run the request
  pending   -> another request with this key is still running: 409
  completed -> same payload: replay the stored response; different payload: 409
A request that fails releases its key, so the client can fix the problem and retry.
"""

import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.exceptions import (
    IdempotencyInProgressError,
    IdempotencyKeyReusedError,
    IdempotencyUnavailableError,
)

COMPLETED_TTL_SECONDS = 24 * 60 * 60
PENDING_TTL_SECONDS = 60  # a crashed request must not lock its key for a day

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StoredResponse:
    status: int
    body: dict[str, Any]


class IdempotentReplay(Exception):  # noqa: N818 - control flow, not an error
    """Raised to short-circuit a request with the stored response of an earlier identical one."""

    def __init__(self, response: StoredResponse) -> None:
        super().__init__("idempotent replay")
        self.response = response


def fingerprint(payload: bytes, *scope_parts: str) -> str:
    """Hash of the request, so a key reused with a different body is detected."""
    try:
        canonical = json.dumps(json.loads(payload), sort_keys=True, separators=(",", ":"))
    except ValueError:
        canonical = payload.decode(errors="replace")
    return hashlib.sha256("|".join([*scope_parts, canonical]).encode()).hexdigest()


class IdempotencyStore:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    @staticmethod
    def _key(scope: str, key: str) -> str:
        return f"idem:{scope}:{hashlib.sha256(key.encode()).hexdigest()}"

    async def begin(self, scope: str, key: str, request_fingerprint: str) -> StoredResponse | None:
        """Claim the key, or return the stored response for a replay. Raises on conflicts."""
        redis_key = self._key(scope, key)
        pending = json.dumps({"state": "pending", "fp": request_fingerprint})
        try:
            for _ in range(2):  # the second pass covers a key that expired between SET and GET
                if await self._redis.set(redis_key, pending, nx=True, ex=PENDING_TTL_SECONDS):
                    return None
                raw = await self._redis.get(redis_key)
                if raw is not None:
                    break
            else:  # pragma: no cover - requires two expiries in a row
                raise IdempotencyInProgressError()
        except RedisError as exc:
            logger.warning("idempotency store unavailable: %s", type(exc).__name__)
            raise IdempotencyUnavailableError() from exc

        stored = json.loads(raw)
        if stored["fp"] != request_fingerprint:
            raise IdempotencyKeyReusedError()
        if stored["state"] == "pending":
            raise IdempotencyInProgressError()
        return StoredResponse(status=stored["status"], body=stored["body"])

    async def complete(
        self, scope: str, key: str, request_fingerprint: str, response: StoredResponse
    ) -> None:
        value = json.dumps(
            {
                "state": "completed",
                "fp": request_fingerprint,
                "status": response.status,
                "body": response.body,
            }
        )
        try:
            await self._redis.set(self._key(scope, key), value, ex=COMPLETED_TTL_SECONDS)
        except RedisError:
            logger.warning("could not store idempotent response; the pending marker will expire")

    async def abort(self, scope: str, key: str) -> None:
        try:
            await self._redis.delete(self._key(scope, key))
        except RedisError:
            logger.warning("could not release idempotency key; it will expire on its own")
