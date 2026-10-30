from fastapi import APIRouter, status

from app.schemas.health import HealthStatus, ReadinessStatus
from app.services.health import HealthService

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    response_model=HealthStatus,
    status_code=status.HTTP_200_OK,
    operation_id="health_live",
    summary="Liveness probe",
    description="Returns 200 while the process is running. Does not touch dependencies.",
)
async def health_live() -> HealthStatus:
    return HealthStatus(status="ok")


@router.get(
    "/health/ready",
    response_model=ReadinessStatus,
    status_code=status.HTTP_200_OK,
    operation_id="health_ready",
    summary="Readiness probe",
    description=(
        "Reports the state of the database and Redis. Currently returns placeholders "
        "(`not_configured`); real checks arrive in Phase 1."
    ),
)
async def health_ready() -> ReadinessStatus:
    checks = await HealthService().check_readiness()
    return ReadinessStatus(status="ok", checks=checks)
