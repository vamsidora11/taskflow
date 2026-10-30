from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=create_app(enable_docs=True)), base_url="http://test"
    ) as c:
        yield c


async def test_health_live(client: AsyncClient) -> None:
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_health_ready(client: AsyncClient) -> None:
    resp = await client.get("/health/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert set(body["checks"]) == {"database", "redis"}


async def test_docs_enabled(client: AsyncClient) -> None:
    assert (await client.get("/docs")).status_code == 200
    assert (await client.get("/api/v1/openapi.json")).status_code == 200


async def test_docs_disabled() -> None:
    transport = ASGITransport(app=create_app(enable_docs=False))
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        assert (await c.get("/docs")).status_code == 404
        assert (await c.get("/api/v1/openapi.json")).status_code == 404
