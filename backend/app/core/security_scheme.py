from fastapi.security import HTTPBearer

bearer_scheme = HTTPBearer(
    scheme_name="BearerAuth",
    description=(
        "Access token from `POST /api/v1/auth/login` or `/auth/refresh`. Expires after 15 minutes."
    ),
    auto_error=True,
)
