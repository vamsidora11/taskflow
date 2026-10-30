import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.exceptions import AppError
from app.schemas.errors import ErrorDetail, ErrorResponse
from app.services.idempotency import IdempotentReplay

logger = logging.getLogger(__name__)

_STATUS_CODES = {
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    429: "RATE_LIMITED",
}


def request_id_of(request: Request) -> str:
    return str(getattr(request.state, "request_id", "unknown"))


def error_response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body = ErrorResponse(
        error=ErrorDetail(code=code, message=message, request_id=request_id_of(request))
    )
    return JSONResponse(body.model_dump(), status_code=status_code, headers=headers)


async def app_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)
    headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
    return error_response(request, exc.status_code, exc.code, exc.message, headers)


async def http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    code = _STATUS_CODES.get(exc.status_code, "HTTP_ERROR")
    headers = dict(exc.headers) if exc.headers else None
    if exc.status_code == 401:
        headers = {**(headers or {}), "WWW-Authenticate": "Bearer"}
    return error_response(request, exc.status_code, code, str(exc.detail), headers)


async def validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    # Field locations and messages only. Never echo the submitted input: it may hold passwords.
    problems = "; ".join(
        f"{'.'.join(str(p) for p in e['loc'] if p != 'body')}: {e['msg']}" for e in exc.errors()
    )
    return error_response(request, 422, "VALIDATION_ERROR", problems or "Invalid request")


async def idempotent_replay_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, IdempotentReplay)
    return JSONResponse(
        exc.response.body,
        status_code=exc.response.status,
        headers={"Idempotent-Replay": "true"},
    )


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled error (request_id=%s)", request_id_of(request))
    return error_response(request, 500, "INTERNAL_ERROR", "Internal server error")


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(IdempotentReplay, idempotent_replay_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)
