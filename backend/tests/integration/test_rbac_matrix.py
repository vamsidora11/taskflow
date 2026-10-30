"""Every cell of the RBAC matrix, end to end through real tokens and `require_permission`.

A probe route is mounted per permission so cells for features that do not exist yet (boards,
tasks, comments, audit) are exercised through the same dependency those features will use.
Then every real organization endpoint is checked for every role.
"""

import uuid
from collections.abc import AsyncIterator

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.api.deps import get_email_sender, get_factory, require_permission
from app.core.permissions import Permission, Role, has_permission
from app.main import create_app
from tests.db_utils import DbUrls
from tests.helpers import Actor, Mailbox, OrgSetup, create_org

ROLES = [r.value for r in Role]


def _mount_probes(app: FastAPI) -> None:
    for permission in Permission:

        async def probe() -> dict[str, bool]:
            return {"ok": True}

        app.get(
            f"/_probe/{permission.value}",
            dependencies=[Depends(require_permission(permission))],
        )(probe)


@pytest.fixture
async def probe_api(database: DbUrls) -> AsyncIterator[AsyncClient]:
    engine = create_async_engine(database.app, pool_size=5, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    app = create_app()
    app.dependency_overrides[get_factory] = lambda: factory
    app.dependency_overrides[get_email_sender] = lambda: Mailbox()
    _mount_probes(app)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as client:
        yield client
    await engine.dispose()


@pytest.fixture
async def org(probe_api: AsyncClient, admin_engine: AsyncEngine) -> OrgSetup:
    return await create_org(probe_api, admin_engine)


@pytest.mark.parametrize("permission", list(Permission), ids=lambda p: p.value)
@pytest.mark.parametrize("role", ROLES)
async def test_probe_route_matches_the_matrix(
    probe_api: AsyncClient, org: OrgSetup, permission: Permission, role: str
) -> None:
    actor = org.actor(role)
    resp = await probe_api.get(f"/_probe/{permission.value}", headers=actor.headers)
    if has_permission(role, permission):
        assert resp.status_code == 200
    else:
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "PERMISSION_DENIED"


@pytest.mark.parametrize("permission", list(Permission), ids=lambda p: p.value)
async def test_probe_route_without_a_token_is_401_not_403(
    probe_api: AsyncClient, permission: Permission
) -> None:
    assert (await probe_api.get(f"/_probe/{permission.value}")).status_code == 401


# --- real organization endpoints, every role -------------------------------------------------


async def _call(api: AsyncClient, org: OrgSetup, endpoint: str, actor: Actor) -> int:
    other = org.member.user_id  # target for member-management calls
    if endpoint == "get_org":
        return (await api.get("/api/v1/org", headers=actor.headers)).status_code
    if endpoint == "patch_org":
        resp = await api.patch("/api/v1/org", json={"name": "Renamed"}, headers=actor.headers)
    elif endpoint == "list_members":
        resp = await api.get("/api/v1/org/members", headers=actor.headers)
    elif endpoint == "invite":
        resp = await api.post(
            "/api/v1/org/invitations",
            json={"email": f"x-{uuid.uuid4().hex[:8]}@example.com", "role": "member"},
            headers=actor.headers,
        )
    elif endpoint == "change_role":
        resp = await api.patch(
            f"/api/v1/org/members/{other}", json={"role": "member"}, headers=actor.headers
        )
    elif endpoint == "remove_member":
        # Target a user that does not exist: authorization must fail before existence is checked.
        resp = await api.delete(f"/api/v1/org/members/{uuid.uuid4()}", headers=actor.headers)
    else:
        raise AssertionError(endpoint)
    return resp.status_code


# endpoint -> (permission, status for a caller that holds it)
ENDPOINTS = {
    "get_org": (Permission.ORG_VIEW, 200),
    "patch_org": (Permission.ORG_UPDATE, 200),
    "list_members": (Permission.MEMBER_VIEW, 200),
    "invite": (Permission.MEMBER_INVITE, 201),
    "change_role": (Permission.MEMBER_CHANGE_ROLE, 200),
    "remove_member": (Permission.MEMBER_REMOVE, 404),  # allowed, but the target does not exist
}


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("endpoint", list(ENDPOINTS))
async def test_organization_endpoint_matches_the_matrix(
    probe_api: AsyncClient, org: OrgSetup, endpoint: str, role: str
) -> None:
    permission, ok_status = ENDPOINTS[endpoint]
    status = await _call(probe_api, org, endpoint, org.actor(role))
    assert status == (ok_status if has_permission(role, permission) else 403)
