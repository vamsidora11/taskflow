import re
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.request_context import client_ip_var, request_id_var

HEADER = "X-Request-ID"
_SAFE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Attach a request id (client-supplied if well-formed, else generated) to every response
    and expose it, with the client address, to audit and logging via context variables."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        supplied = request.headers.get(HEADER, "")
        request_id = supplied if _SAFE.match(supplied) else f"req_{uuid.uuid4().hex[:12]}"
        request.state.request_id = request_id
        id_token = request_id_var.set(request_id)
        ip_token = client_ip_var.set(request.client.host if request.client else None)
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(id_token)
            client_ip_var.reset(ip_token)
        response.headers[HEADER] = request_id
        return response
