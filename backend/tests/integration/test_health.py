from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.v1.health import get_health_service
from app.main import create_app
from app.services.health import HealthService, ProbeState


class StubHealthService(HealthService):
    def __init__(self, database: ProbeState, redis: ProbeState) -> None:
        self._states: dict[str, ProbeState] = {"database": database, "redis": redis}

    async def check_readiness(self) -> dict[str, ProbeState]:
        return self._states


def make_client(service: HealthService | None = None, enable_docs: bool = True) -> AsyncClient:
    app = create_app(enable_docs=enable_docs)
    if service is not None:
        app.dependency_overrides[get_health_service] = lambda: service
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with make_client(StubHealthService("ok", "ok")) as c:
        yield c


async def test_health_live(client: AsyncClient) -> None:
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_health_ready_when_dependencies_are_up(client: AsyncClient) -> None:
    resp = await client.get("/health/ready")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "checks": {"database": "ok", "redis": "ok"}}


@pytest.mark.parametrize(
    ("database", "redis"), [("error", "ok"), ("ok", "error"), ("error", "error")]
)
async def test_health_ready_is_503_when_a_dependency_is_down(
    database: ProbeState, redis: ProbeState
) -> None:
    async with make_client(StubHealthService(database, redis)) as c:
        resp = await c.get("/health/ready")
    assert resp.status_code == 503
    assert resp.json() == {
        "status": "unavailable",
        "checks": {"database": database, "redis": redis},
    }


async def test_docs_enabled(client: AsyncClient) -> None:
    assert (await client.get("/docs")).status_code == 200
    assert (await client.get("/api/v1/openapi.json")).status_code == 200


async def test_docs_disabled() -> None:
    async with make_client(enable_docs=False) as c:
        assert (await c.get("/docs")).status_code == 404
        assert (await c.get("/api/v1/openapi.json")).status_code == 404
