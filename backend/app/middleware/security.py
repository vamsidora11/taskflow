import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import settings
from app.core.logging import redact
from app.core.request_context import client_ip_var, request_id_var

access_logger = logging.getLogger("taskflow.access")

_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Baseline browser hardening on every response, including errors."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        for name, value in _HEADERS.items():
            response.headers.setdefault(name, value)
        if settings.app_env in {"production", "staging"}:
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        budget = getattr(request.state, "rate_limit", None)
        if budget is not None:
            response.headers.setdefault("X-RateLimit-Limit", str(budget[0]))
            response.headers.setdefault("X-RateLimit-Remaining", str(budget[1]))
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")  # tokens and tenant data
        return response


class AccessLogMiddleware(BaseHTTPMiddleware):
    """One structured line per request. Never logs headers, bodies or query strings, and masks
    the invitation token that travels in the URL path."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        started = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            access_logger.info(
                "request",
                extra={
                    "fields": {
                        "method": request.method,
                        "path": redact(request.url.path),
                        "status": status,
                        "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                        "client_ip": client_ip_var.get(),
                        "user_id": getattr(request.state, "user_id", None),
                        "request_id": request_id_var.get(),
                    }
                },
            )
