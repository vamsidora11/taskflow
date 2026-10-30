"""Per-request values that deep layers (audit, logging) need without threading them through
every call. Set by the request-id middleware, read-only everywhere else."""

from contextvars import ContextVar

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
client_ip_var: ContextVar[str | None] = ContextVar("client_ip", default=None)
