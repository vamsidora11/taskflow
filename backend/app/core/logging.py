"""Structured JSON logging with request ids and secret redaction (PLAN.md sections 7 and 12).

Every record goes through `redact` before it is written, so a token or password that reaches a log
call by mistake (an exception message, a copied header) is masked rather than stored.
"""

import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Any

from app.core.request_context import request_id_var

REDACTED = "[REDACTED]"
_PATTERNS = [
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+"), "Bearer " + REDACTED),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*"), "[JWT]"),
    (
        re.compile(
            r"""(?ix)(["']?(?:password|passwd|secret|token|authorization|api[_-]?key|cookie)
            ["']?\s*[:=]\s*)(["']?)[^\s,;"'}]+\2"""
        ),
        r"\1" + REDACTED,
    ),
    (re.compile(r"(?i)(/org/invitations/)[^/\s?]+(/accept)"), r"\1" + REDACTED + r"\2"),
]


def redact(text: str) -> str:
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage())
        record.args = None
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage()),
            "request_id": request_id_var.get(),
        }
        extra = getattr(record, "fields", None)
        if isinstance(extra, dict):
            payload.update(extra)
        if record.exc_info:
            payload["exception"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, default=str)


_MARK = "_taskflow_handler"


def configure_logging(level: str = "INFO", *, as_json: bool = True) -> None:
    """Idempotent. Installs one stdout handler on the root logger and silences uvicorn's own
    access log (the application logs each request itself, with the path redacted)."""
    root = logging.getLogger()
    root.setLevel(level.upper())
    if not any(getattr(h, _MARK, False) for h in root.handlers):
        handler = logging.StreamHandler(sys.stdout)
        setattr(handler, _MARK, True)
        handler.addFilter(RedactingFilter())
        handler.setFormatter(
            JsonFormatter()
            if as_json
            else logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )
        root.addHandler(handler)
    access = logging.getLogger("uvicorn.access")
    access.handlers.clear()
    access.propagate = False
