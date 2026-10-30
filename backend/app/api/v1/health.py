from fastapi import APIRouter, Depends, Response, status

from app.db.redis import get_redis
from app.db.session import get_engine
from app.schemas.health import HealthStatus, ReadinessStatus
from app.services.health import HealthService

router = APIRouter(tags=["health"])


def get_health_service() -> HealthService:
    return HealthService(get_engine(), get_redis())


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
        "Pings PostgreSQL and Redis. Returns 200 when both respond, or 503 with the same "
        "body shape when either fails."
    ),
    responses={503: {"model": ReadinessStatus, "description": "A dependency is unreachable"}},
)
async def health_ready(
    response: Response, service: HealthService = Depends(get_health_service)
) -> ReadinessStatus:
    checks = await service.check_readiness()
    if all(state == "ok" for state in checks.values()):
        return ReadinessStatus(status="ok", checks=checks)
    response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessStatus(status="unavailable", checks=checks)
