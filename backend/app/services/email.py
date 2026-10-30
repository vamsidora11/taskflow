"""Outgoing email. Services build messages; a sender delivers them after the transaction commits."""

import asyncio
import logging
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage as MimeMessage
from typing import Protocol

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EmailMessage:
    to: str
    subject: str
    body: str


class EmailSender(Protocol):
    async def send(self, message: EmailMessage) -> None: ...


class ConsoleEmailSender:
    """Development transport: prints the whole message, including any invitation link, to stdout.
    This is the one deliberate exception to "never log tokens" and it only exists behind
    EMAIL_BACKEND=console; production must use `smtp`.

    It writes to stdout rather than through `logging` on purpose: until structured logging is
    configured (Phase 6) the root logger drops INFO records, and a developer who cannot see the
    link cannot accept the invitation."""

    async def send(self, message: EmailMessage) -> None:
        print(
            f"--- DEV EMAIL ---\nTo: {message.to}\nSubject: {message.subject}\n\n"
            f"{message.body}\n--- END DEV EMAIL ---",
            flush=True,
        )


class SmtpEmailSender:
    async def send(self, message: EmailMessage) -> None:
        await asyncio.to_thread(self._send_blocking, message)

    @staticmethod
    def _send_blocking(message: EmailMessage) -> None:
        mime = MimeMessage()
        mime["From"] = settings.email_from
        mime["To"] = message.to
        mime["Subject"] = message.subject
        mime.set_content(message.body)
        if not settings.smtp_host:
            raise RuntimeError("SMTP_HOST is not configured")
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
            smtp.starttls()
            if settings.smtp_user and settings.smtp_password:
                smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(mime)


def build_email_sender() -> EmailSender:
    return SmtpEmailSender() if settings.email_backend == "smtp" else ConsoleEmailSender()


async def deliver_email(sender: EmailSender, message: EmailMessage) -> None:
    """Send without ever failing the request: the invitation already exists and can be re-sent.

    Only the recipient is logged on failure, never the body (it carries a secret link).
    """
    try:
        await sender.send(message)
    except Exception:
        logger.exception("failed to deliver email to %s", message.to)
