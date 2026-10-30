from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.session import SessionFactory
from scripts.seed import ACME_ADMIN, ACME_MANAGER, ACME_MEMBER, DEMO_PASSWORD, GLOBEX_ADMIN, seed
from tests.helpers import bearer


async def login(api: AsyncClient, email: str) -> dict[str, str]:
    api.cookies.clear()
    resp = await api.post("/api/v1/auth/login", json={"email": email, "password": DEMO_PASSWORD})
    assert resp.status_code == 200, (email, resp.text)
    return bearer(resp.json()["access_token"])


async def test_seeding_builds_two_working_organizations_and_is_idempotent(
    api: AsyncClient, app_session_factory: SessionFactory, admin_engine: AsyncEngine
) -> None:
    assert await seed(app_session_factory) is True
    assert await seed(app_session_factory) is False  # second run changes nothing

    async with admin_engine.connect() as conn:
        users = (
            await conn.execute(
                text("SELECT count(*) FROM users WHERE email IN (:a, :b, :c, :d)"),
                {"a": ACME_ADMIN, "b": ACME_MANAGER, "c": ACME_MEMBER, "d": GLOBEX_ADMIN},
            )
        ).scalar_one()
    assert users == 4  # alan is one user in two organizations, not two users

    ada = await login(api, ACME_ADMIN)
    boards = (await api.get("/api/v1/boards", headers=ada)).json()["items"]
    assert {b["name"] for b in boards} == {"Product Roadmap", "Marketing Launch"}
    roadmap = next(b for b in boards if b["name"] == "Product Roadmap")
    tasks = (await api.get(f"/api/v1/boards/{roadmap['id']}/tasks", headers=ada)).json()["items"]
    assert len(tasks) == 8
    assert {t["priority"] for t in tasks} == {"low", "medium", "high", "urgent"}
    first = tasks[0]
    comments = await api.get(f"/api/v1/tasks/{first['id']}/comments", headers=ada)
    assert comments.status_code == 200

    members = (await api.get("/api/v1/org/members", headers=ada)).json()["items"]
    assert {m["role"] for m in members} == {"admin", "manager", "member"}
    log = (await api.get("/api/v1/audit-logs", params={"limit": 100}, headers=ada)).json()["items"]
    assert {"member.joined", "task.created", "board.created", "comment.created"} <= {
        e["action"] for e in log
    }


async def test_the_shared_member_sees_both_organizations_and_cannot_cross_them(
    api: AsyncClient, app_session_factory: SessionFactory
) -> None:
    await seed(app_session_factory)
    alan = await login(api, ACME_MEMBER)
    me = (await api.get("/api/v1/auth/me", headers=alan)).json()
    assert {o["name"] for o in me["organizations"]} == {"Acme Corp", "Globex Inc"}

    hank = await login(api, GLOBEX_ADMIN)
    globex_boards = (await api.get("/api/v1/boards", headers=hank)).json()["items"]
    assert [b["name"] for b in globex_boards] == ["Operations"]
    assert me["active_organization"]["name"] == "Acme Corp"  # earliest membership
    acme_boards = (await api.get("/api/v1/boards", headers=alan)).json()["items"]
    assert "Operations" not in {b["name"] for b in acme_boards}  # Globex data stays in Globex
