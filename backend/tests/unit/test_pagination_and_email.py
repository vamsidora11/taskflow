import base64
import smtplib
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from app.core.config import settings
from app.core.exceptions import InvalidCursorError
from app.core.pagination import decode_cursor, encode_cursor
from app.services.email import (
    ConsoleEmailSender,
    EmailMessage,
    SmtpEmailSender,
    build_email_sender,
    deliver_email,
)


def test_cursor_round_trip() -> None:
    ts, row_id = datetime(2026, 10, 30, 9, 0, 1, 123456, tzinfo=UTC), uuid.uuid4()
    assert decode_cursor(encode_cursor(ts, row_id)) == (ts, row_id)


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "not-base64!!",
        base64.urlsafe_b64encode(b"not json").decode(),
        base64.urlsafe_b64encode(b'{"t": "x"}').decode(),
        base64.urlsafe_b64encode(b'{"t": "2026-01-01T00:00:00+00:00", "i": "nope"}').decode(),
    ],
)
def test_malformed_cursors_are_rejected(bad: str) -> None:
    with pytest.raises(InvalidCursorError):
        decode_cursor(bad)


def test_the_email_backend_follows_the_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "email_backend", "console")
    assert isinstance(build_email_sender(), ConsoleEmailSender)
    monkeypatch.setattr(settings, "email_backend", "smtp")
    assert isinstance(build_email_sender(), SmtpEmailSender)


async def test_console_sender_prints_to_stdout_so_the_link_is_visible(
    capsys: pytest.CaptureFixture[str],
) -> None:
    message = EmailMessage(to="a@example.com", subject="Invite", body="Open /accept?token=abc")
    await ConsoleEmailSender().send(message)
    out = capsys.readouterr().out
    assert "a@example.com" in out
    assert "Open /accept?token=abc" in out


class FakeSmtp:
    instances: list["FakeSmtp"] = []

    def __init__(self, host: str, port: int, timeout: float) -> None:
        self.host, self.port = host, port
        self.calls: list[str] = []
        self.sent: Any = None
        FakeSmtp.instances.append(self)

    def __enter__(self) -> "FakeSmtp":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def starttls(self) -> None:
        self.calls.append("starttls")

    def login(self, user: str, password: str) -> None:
        self.calls.append(f"login:{user}")

    def send_message(self, message: Any) -> None:
        self.calls.append("send")
        self.sent = message


async def test_smtp_sender_uses_starttls_and_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeSmtp.instances.clear()
    monkeypatch.setattr(smtplib, "SMTP", FakeSmtp)
    monkeypatch.setattr(settings, "smtp_host", "mail.example.com")
    monkeypatch.setattr(settings, "smtp_user", "mailer")
    monkeypatch.setattr(settings, "smtp_password", "pw")
    await SmtpEmailSender().send(EmailMessage(to="a@example.com", subject="Hi", body="Body"))
    smtp = FakeSmtp.instances[0]
    assert smtp.host == "mail.example.com"
    assert smtp.calls == ["starttls", "login:mailer", "send"]
    assert smtp.sent["To"] == "a@example.com"
    assert smtp.sent["Subject"] == "Hi"


async def test_smtp_sender_requires_a_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "smtp_host", None)
    with pytest.raises(RuntimeError):
        await SmtpEmailSender().send(EmailMessage(to="a@example.com", subject="s", body="b"))


class ExplodingSender:
    async def send(self, message: EmailMessage) -> None:
        raise ConnectionError("smtp down")


async def test_deliver_email_swallows_failures_and_never_logs_the_body(
    caplog: pytest.LogCaptureFixture,
) -> None:
    message = EmailMessage(to="a@example.com", subject="s", body="secret-link-token-123")
    await deliver_email(ExplodingSender(), message)  # must not raise
    assert "a@example.com" in caplog.text
    assert "secret-link-token-123" not in caplog.text
