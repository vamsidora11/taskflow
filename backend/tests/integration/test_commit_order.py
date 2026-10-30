"""Writes must be durable before the client sees the response.

FastAPI runs a `yield` dependency's cleanup after the response is sent unless it is declared with
`scope="function"`. The tenant session commits in its cleanup, so with the default scope a client
could receive its 2xx before the commit, and a failed commit would never reach it.
"""

import json

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.helpers import create_org


async def test_a_write_is_committed_before_the_response_starts(
    api: AsyncClient, admin_engine: AsyncEngine
) -> None:
    org = await create_org(api, admin_engine)
    app = api._transport.app  # type: ignore[attr-defined]
    body = json.dumps({"name": "Visible Before Response"}).encode()
    observed: dict[str, object] = {}

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message: dict[str, object]) -> None:
        if message["type"] == "http.response.start":
            observed["status"] = message["status"]
            # A separate connection, at the instant the response is about to go out.
            async with admin_engine.connect() as conn:
                observed["name_in_db"] = (
                    await conn.execute(
                        text("SELECT name FROM organizations WHERE id = :id"), {"id": org.org_id}
                    )
                ).scalar_one()

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "PATCH",
        "scheme": "https",
        "path": "/api/v1/org",
        "raw_path": b"/api/v1/org",
        "query_string": b"",
        "server": ("test", 443),
        "client": ("127.0.0.1", 1234),
        "headers": [
            (b"authorization", f"Bearer {org.admin.token}".encode()),
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
        ],
    }
    await app(scope, receive, send)
    assert observed == {"status": 200, "name_in_db": "Visible Before Response"}
