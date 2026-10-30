from fastapi import FastAPI

from app.api.error_handlers import register_error_handlers
from app.api.v1 import auth, boards, health, organization, tasks
from app.core.config import settings
from app.middleware.request_id import RequestIdMiddleware

TAGS_METADATA = [
    {
        "name": "auth",
        "description": "Signup, login, token refresh, logout, and organization switching.",
    },
    {"name": "organization", "description": "Organization settings, members, and invitations."},
    {"name": "boards", "description": "Boards and their columns."},
    {"name": "tasks", "description": "Task CRUD, filtering, and moving between columns."},
    {"name": "comments", "description": "Comments on tasks."},
    {"name": "audit", "description": "Append-only activity log for compliance review."},
    {"name": "health", "description": "Liveness and readiness probes."},
]


def create_app(enable_docs: bool | None = None) -> FastAPI:
    docs_on = settings.enable_docs if enable_docs is None else enable_docs
    app = FastAPI(
        title="TaskFlow API",
        version="1.0.0",
        summary="Multi-tenant task management platform",
        description=(
            "REST API for organizations, role-based boards and tasks, comments, and audit logs.\n\n"
            "**Authentication:** call `POST /api/v1/auth/login`, copy the `access_token`, "
            "and paste it into the Authorize dialog. Access tokens expire after 15 minutes; "
            "use `POST /api/v1/auth/refresh` to rotate them.\n\n"
            "**Tenancy:** the active organization is embedded in the access token. "
            "Use `POST /api/v1/auth/switch-org` to change it.\n\n"
            "**Errors:** every error, including validation failures (`422`), uses the envelope "
            '`{"error": {"code", "message", "request_id"}}`.'
        ),
        contact={"name": "TaskFlow Team", "email": "support@example.com"},
        license_info={"name": "MIT"},
        openapi_tags=TAGS_METADATA,
        openapi_url="/api/v1/openapi.json" if docs_on else None,
        docs_url="/docs" if docs_on else None,
        redoc_url="/redoc" if docs_on else None,
        swagger_ui_parameters={
            "persistAuthorization": True,
            "docExpansion": "none",
            "defaultModelsExpandDepth": -1,
            "displayRequestDuration": True,
        },
    )
    app.add_middleware(RequestIdMiddleware)
    register_error_handlers(app)
    app.include_router(auth.router)
    app.include_router(organization.router)
    app.include_router(boards.router)
    app.include_router(tasks.router)
    app.include_router(health.router)
    return app


app = create_app()
