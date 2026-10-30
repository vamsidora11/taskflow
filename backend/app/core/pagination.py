"""Opaque cursor encoding for keyset pagination (PLAN.md section 10)."""

import base64
import json
import uuid
from datetime import datetime

from app.core.exceptions import InvalidCursorError

DEFAULT_LIMIT = 50
MAX_LIMIT = 100


def encode_cursor(created_at: datetime, row_id: uuid.UUID) -> str:
    raw = json.dumps({"t": created_at.isoformat(), "i": str(row_id)}).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode()))
        return datetime.fromisoformat(data["t"]), uuid.UUID(data["i"])
    except (ValueError, KeyError, TypeError) as exc:
        raise InvalidCursorError() from exc
