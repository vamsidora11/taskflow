import asyncio
import base64
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.helpers import (
    Actor,
    OrgSetup,
    add_member,
    bearer,
    create_org,
    signup,
)


@pytest.fixture
async def org(api: AsyncClient, admin_engine: AsyncEngine) -> OrgSetup:
    return await create_org(api, admin_engine)


# --- organization settings -------------------------------------------------------------------


async def test_get_organization(api: AsyncClient, org: OrgSetup) -> None:
    resp = await api.get("/api/v1/org", headers=org.member.headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == org.org_id
    assert body["name"].startswith("Org ")
    assert body["slug"]
    assert "created_at" in body


async def test_admin_renames_the_organization_and_slug_stays(
    api: AsyncClient, org: OrgSetup
) -> None:
    before = (await api.get("/api/v1/org", headers=org.admin.headers)).json()
    resp = await api.patch(
        "/api/v1/org", json={"name": "Acme Corporation"}, headers=org.admin.headers
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Acme Corporation"
    assert resp.json()["slug"] == before["slug"]
    reread = await api.get("/api/v1/org", headers=org.member.headers)
    assert reread.json()["name"] == "Acme Corporation"


async def test_empty_patch_is_a_no_op_and_blank_name_is_rejected(
    api: AsyncClient, org: OrgSetup
) -> None:
    before = (await api.get("/api/v1/org", headers=org.admin.headers)).json()
    assert (await api.patch("/api/v1/org", json={}, headers=org.admin.headers)).json() == before
    blank = await api.patch("/api/v1/org", json={"name": ""}, headers=org.admin.headers)
    assert blank.status_code == 422
    assert blank.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_a_tenant_only_ever_sees_its_own_organization(
    api: AsyncClient, org: OrgSetup
) -> None:
    other = await signup(api, org="Other Org")
    mine = (await api.get("/api/v1/org", headers=org.admin.headers)).json()
    theirs = (await api.get("/api/v1/org", headers=bearer(other["access_token"]))).json()
    assert mine["id"] == org.org_id
    assert theirs["id"] == other["organization_id"] != org.org_id


# --- listing members -------------------------------------------------------------------------


async def test_list_members_returns_everyone_with_roles(api: AsyncClient, org: OrgSetup) -> None:
    resp = await api.get("/api/v1/org/members", headers=org.member.headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["next_cursor"] is None
    roles = {m["user_id"]: m["role"] for m in body["items"]}
    assert roles == {
        org.admin.user_id: "admin",
        org.manager.user_id: "manager",
        org.member.user_id: "member",
    }
    first = body["items"][0]
    assert set(first) == {"user_id", "email", "full_name", "role", "joined_at"}
    assert "password" not in str(body)


async def test_list_members_does_not_leak_other_organizations(
    api: AsyncClient, org: OrgSetup
) -> None:
    outsider = await signup(api, org="Elsewhere")
    resp = await api.get("/api/v1/org/members", headers=org.admin.headers)
    emails = {m["email"] for m in resp.json()["items"]}
    assert outsider["email"] not in emails
    assert len(emails) == 3


async def test_members_paginate_with_a_stable_cursor(
    api: AsyncClient, admin_engine: AsyncEngine, org: OrgSetup
) -> None:
    for _ in range(3):
        await add_member(api, admin_engine, org.org_id, "member")  # 6 members in total

    seen: list[str] = []
    cursor: str | None = None
    pages = 0
    while True:
        params: dict[str, str | int] = {"limit": 2}
        if cursor:
            params["cursor"] = cursor
        body = (
            await api.get("/api/v1/org/members", params=params, headers=org.admin.headers)
        ).json()
        assert len(body["items"]) <= 2
        seen += [m["user_id"] for m in body["items"]]
        pages += 1
        cursor = body["next_cursor"]
        if cursor is None:
            break
    assert pages == 3
    assert len(seen) == len(set(seen)) == 6


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 101}, {"limit": "abc"}])
async def test_list_members_rejects_a_bad_limit(
    api: AsyncClient, org: OrgSetup, params: dict[str, str | int]
) -> None:
    resp = await api.get("/api/v1/org/members", params=params, headers=org.admin.headers)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_list_members_rejects_a_malformed_cursor(api: AsyncClient, org: OrgSetup) -> None:
    junk = base64.urlsafe_b64encode(b"not json").decode()
    resp = await api.get("/api/v1/org/members", params={"cursor": junk}, headers=org.admin.headers)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "INVALID_CURSOR"


# --- changing roles --------------------------------------------------------------------------


async def test_admin_promotes_a_member_and_it_takes_effect_immediately(
    api: AsyncClient, org: OrgSetup
) -> None:
    denied = await api.patch("/api/v1/org", json={"name": "X"}, headers=org.member.headers)
    assert denied.status_code == 403

    resp = await api.patch(
        f"/api/v1/org/members/{org.member.user_id}",
        json={"role": "admin"},
        headers=org.admin.headers,
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == "admin"
    assert resp.json()["user_id"] == org.member.user_id

    # The member's existing access token now carries admin rights: role comes from the database.
    allowed = await api.patch("/api/v1/org", json={"name": "Now Admin"}, headers=org.member.headers)
    assert allowed.status_code == 200


async def test_demoting_takes_effect_immediately_too(api: AsyncClient, org: OrgSetup) -> None:
    resp = await api.patch(
        f"/api/v1/org/members/{org.manager.user_id}",
        json={"role": "member"},
        headers=org.admin.headers,
    )
    assert resp.status_code == 200
    members = await api.get("/api/v1/org/members", headers=org.manager.headers)
    roles = {m["user_id"]: m["role"] for m in members.json()["items"]}
    assert roles[org.manager.user_id] == "member"


async def test_changing_the_role_of_a_non_member_is_404(api: AsyncClient, org: OrgSetup) -> None:
    stranger = await signup(api, org="Stranger Org")
    stranger_id = (
        await api.get("/api/v1/auth/me", headers=bearer(stranger["access_token"]))
    ).json()["user"]["id"]
    for target in (stranger_id, str(uuid.uuid4())):
        resp = await api.patch(
            f"/api/v1/org/members/{target}", json={"role": "member"}, headers=org.admin.headers
        )
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "MEMBER_NOT_FOUND"


async def test_an_invalid_role_is_rejected(api: AsyncClient, org: OrgSetup) -> None:
    resp = await api.patch(
        f"/api/v1/org/members/{org.member.user_id}",
        json={"role": "owner"},
        headers=org.admin.headers,
    )
    assert resp.status_code == 422


async def test_the_last_admin_cannot_demote_themselves(api: AsyncClient, org: OrgSetup) -> None:
    resp = await api.patch(
        f"/api/v1/org/members/{org.admin.user_id}",
        json={"role": "member"},
        headers=org.admin.headers,
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "LAST_ADMIN"
    still = await api.get("/api/v1/org/members", headers=org.admin.headers)
    admin_row = next(m for m in still.json()["items"] if m["user_id"] == org.admin.user_id)
    assert admin_row["role"] == "admin"


async def test_an_admin_can_step_down_once_another_admin_exists(
    api: AsyncClient, org: OrgSetup
) -> None:
    await api.patch(
        f"/api/v1/org/members/{org.manager.user_id}",
        json={"role": "admin"},
        headers=org.admin.headers,
    )
    resp = await api.patch(
        f"/api/v1/org/members/{org.admin.user_id}",
        json={"role": "member"},
        headers=org.admin.headers,
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == "member"


async def test_re_assigning_admin_to_the_only_admin_is_allowed(
    api: AsyncClient, org: OrgSetup
) -> None:
    resp = await api.patch(
        f"/api/v1/org/members/{org.admin.user_id}",
        json={"role": "admin"},
        headers=org.admin.headers,
    )
    assert resp.status_code == 200


async def test_two_admins_cannot_demote_each_other_at_the_same_time(
    api: AsyncClient, admin_engine: AsyncEngine, org: OrgSetup
) -> None:
    second = await add_member(api, admin_engine, org.org_id, "admin")

    async def demote(actor: Actor, target: Actor) -> int:
        resp = await api.patch(
            f"/api/v1/org/members/{target.user_id}", json={"role": "member"}, headers=actor.headers
        )
        return resp.status_code

    results = await asyncio.gather(demote(org.admin, second), demote(second, org.admin))
    assert sorted(results)[0] == 200
    assert results.count(200) == 1  # the other attempt was refused
    async with admin_engine.connect() as conn:
        admins = (
            await conn.execute(
                text(
                    "SELECT count(*) FROM memberships WHERE organization_id = :o AND role = 'admin'"
                ),
                {"o": org.org_id},
            )
        ).scalar_one()
    assert admins == 1


# --- removing members ------------------------------------------------------------------------


async def test_removed_member_loses_access_and_cannot_refresh(
    api: AsyncClient, admin_engine: AsyncEngine, org: OrgSetup
) -> None:
    victim = await add_member(api, admin_engine, org.org_id, "member")
    assert (await api.get("/api/v1/org", headers=victim.headers)).status_code == 200

    resp = await api.delete(f"/api/v1/org/members/{victim.user_id}", headers=org.admin.headers)
    assert resp.status_code == 204

    members = await api.get("/api/v1/org/members", headers=org.admin.headers)
    assert victim.user_id not in {m["user_id"] for m in members.json()["items"]}
    gone = await api.get("/api/v1/org", headers=victim.headers)
    assert gone.status_code == 401
    assert gone.json()["error"]["code"] == "INVALID_TOKEN"


async def test_removal_ends_the_removed_users_sessions_in_that_org(
    api: AsyncClient, admin_engine: AsyncEngine, org: OrgSetup
) -> None:
    victim = await add_member(api, admin_engine, org.org_id, "member")
    login = await api.post(
        "/api/v1/auth/switch-org",
        json={"organization_id": org.org_id},
        headers=victim.headers,
    )
    assert login.status_code == 200  # victim holds a live refresh session for this org
    await api.delete(f"/api/v1/org/members/{victim.user_id}", headers=org.admin.headers)
    assert (await api.post("/api/v1/auth/refresh")).status_code == 401
    async with admin_engine.connect() as conn:
        live = (
            await conn.execute(
                text(
                    "SELECT count(*) FROM refresh_tokens WHERE user_id = :u "
                    "AND organization_id = :o AND revoked_at IS NULL"
                ),
                {"u": victim.user_id, "o": org.org_id},
            )
        ).scalar_one()
    assert live == 0


async def test_removing_a_non_member_is_404(api: AsyncClient, org: OrgSetup) -> None:
    resp = await api.delete(f"/api/v1/org/members/{uuid.uuid4()}", headers=org.admin.headers)
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "MEMBER_NOT_FOUND"


async def test_the_last_admin_cannot_be_removed_even_by_themselves(
    api: AsyncClient, org: OrgSetup
) -> None:
    resp = await api.delete(f"/api/v1/org/members/{org.admin.user_id}", headers=org.admin.headers)
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "LAST_ADMIN"
    assert (await api.get("/api/v1/org", headers=org.admin.headers)).status_code == 200


async def test_an_admin_can_remove_themselves_when_another_admin_exists(
    api: AsyncClient, org: OrgSetup
) -> None:
    await api.patch(
        f"/api/v1/org/members/{org.manager.user_id}",
        json={"role": "admin"},
        headers=org.admin.headers,
    )
    resp = await api.delete(f"/api/v1/org/members/{org.admin.user_id}", headers=org.admin.headers)
    assert resp.status_code == 204
    members = await api.get("/api/v1/org/members", headers=org.manager.headers)
    assert [m["role"] for m in members.json()["items"]].count("admin") == 1


async def test_one_orgs_admin_cannot_manage_another_orgs_members(
    api: AsyncClient, admin_engine: AsyncEngine, org: OrgSetup
) -> None:
    other = await create_org(api, admin_engine)
    for method, body in (("PATCH", {"role": "admin"}), ("DELETE", None)):
        resp = await api.request(
            method,
            f"/api/v1/org/members/{other.member.user_id}",
            json=body,
            headers=org.admin.headers,
        )
        assert resp.status_code == 404
    still = await api.get("/api/v1/org/members", headers=other.admin.headers)
    assert other.member.user_id in {m["user_id"] for m in still.json()["items"]}
