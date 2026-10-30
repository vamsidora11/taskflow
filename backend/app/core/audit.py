"""Audit vocabulary and the helpers that keep audit metadata small, JSON-safe and secret-free."""

import re
import uuid
from datetime import date, datetime
from enum import StrEnum
from typing import Any

REDACTED = "[REDACTED]"
# Any field whose name contains one of these is masked, wherever it appears in the metadata.
_SENSITIVE = re.compile(
    r"pass(word|wd)|secret|token|hash|authorization|cookie|api[_-]?key|credential", re.IGNORECASE
)


class AuditAction(StrEnum):
    AUTH_LOGIN = "auth.login"
    AUTH_LOGIN_FAILED = "auth.login_failed"
    AUTH_REFRESH_REUSE = "auth.refresh_reuse_detected"
    ORG_CREATED = "org.created"
    ORG_UPDATED = "org.updated"
    MEMBER_INVITED = "member.invited"
    MEMBER_JOINED = "member.joined"
    MEMBER_ROLE_CHANGED = "member.role_changed"
    MEMBER_REMOVED = "member.removed"
    BOARD_CREATED = "board.created"
    BOARD_UPDATED = "board.updated"
    BOARD_ARCHIVED = "board.archived"
    TASK_CREATED = "task.created"
    TASK_UPDATED = "task.updated"
    TASK_MOVED = "task.moved"
    TASK_DELETED = "task.deleted"
    COMMENT_CREATED = "comment.created"
    COMMENT_DELETED = "comment.deleted"


def jsonable(value: Any) -> Any:
    """Convert values to something JSON can hold, masking sensitive keys in nested dicts."""
    if isinstance(value, dict):
        return {
            str(k): REDACTED if _SENSITIVE.search(str(k)) else jsonable(v) for k, v in value.items()
        }
    if isinstance(value, list | tuple | set):
        return [jsonable(v) for v in value]
    if isinstance(value, uuid.UUID | date | datetime):
        return str(value) if isinstance(value, uuid.UUID) else value.isoformat()
    if isinstance(value, StrEnum):
        return value.value
    return value


def diff_fields(before: dict[str, Any], after: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """`{field: {"from": old, "to": new}}` for the fields that actually changed.

    Only changed fields are kept, so a rename does not copy an unrelated 5,000-character
    description into the log. Sensitive fields are recorded as changed but never by value.
    """
    changes: dict[str, dict[str, Any]] = {}
    for field in after:
        old, new = before.get(field), after[field]
        if jsonable(old) == jsonable(new):
            continue
        if _SENSITIVE.search(field):
            changes[field] = {"from": REDACTED, "to": REDACTED}
        else:
            changes[field] = {"from": jsonable(old), "to": jsonable(new)}
    return changes
