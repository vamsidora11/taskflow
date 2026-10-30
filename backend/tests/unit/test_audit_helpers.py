import uuid
from datetime import UTC, date, datetime

import pytest

from app.core.audit import REDACTED, AuditAction, diff_fields, jsonable
from app.core.enums import Priority


def test_diff_keeps_only_changed_fields() -> None:
    before = {"title": "Old", "priority": "low", "description": "x" * 5000}
    after = {"title": "New", "priority": "low", "description": "x" * 5000}
    assert diff_fields(before, after) == {"title": {"from": "Old", "to": "New"}}


def test_diff_of_nothing_is_empty() -> None:
    assert diff_fields({"a": 1}, {"a": 1}) == {}


def test_diff_treats_equal_values_of_different_types_as_unchanged() -> None:
    task_id = uuid.uuid4()
    assert diff_fields({"id": task_id}, {"id": str(task_id)}) == {}
    assert diff_fields({"p": Priority.HIGH}, {"p": "high"}) == {}


def test_values_become_json_safe() -> None:
    out = diff_fields(
        {"due": None, "who": None},
        {"due": date(2026, 11, 15), "who": uuid.UUID(int=7)},
    )
    assert out["due"]["to"] == "2026-11-15"
    assert out["who"]["to"] == str(uuid.UUID(int=7))
    assert jsonable(datetime(2026, 1, 2, 3, 4, tzinfo=UTC)) == "2026-01-02T03:04:00+00:00"
    assert jsonable({"a": {1, 2}}) == {"a": [1, 2]} or jsonable({"a": {1, 2}}) == {"a": [2, 1]}


@pytest.mark.parametrize(
    "key",
    [
        "password",
        "new_password",
        "password_hash",
        "access_token",
        "refresh_token",
        "token",
        "Authorization",
        "client_secret",
        "api_key",
        "apikey",
        "Cookie",
        "credentials",
    ],
)
def test_sensitive_keys_are_masked_at_any_depth(key: str) -> None:
    out = jsonable({"safe": 1, "nested": {key: "hunter2", "deeper": [{key: "hunter2"}]}})
    assert out["safe"] == 1
    assert out["nested"][key] == REDACTED
    assert out["nested"]["deeper"][0][key] == REDACTED
    assert "hunter2" not in str(out)


def test_a_changed_sensitive_field_is_recorded_as_changed_but_never_by_value() -> None:
    out = diff_fields({"password_hash": "old-secret"}, {"password_hash": "new-secret"})
    assert out == {"password_hash": {"from": REDACTED, "to": REDACTED}}
    assert "secret" not in str(out)


def test_every_action_in_the_plan_exists() -> None:
    expected = {
        "auth.login",
        "auth.login_failed",
        "auth.refresh_reuse_detected",
        "org.updated",
        "member.invited",
        "member.joined",
        "member.role_changed",
        "member.removed",
        "board.created",
        "board.updated",
        "board.archived",
        "task.created",
        "task.updated",
        "task.moved",
        "task.deleted",
        "comment.created",
        "comment.deleted",
    }
    assert expected <= {a.value for a in AuditAction}
