from typing import Any

from httpx import ASGITransport, AsyncClient

from app.main import TAGS_METADATA, create_app

PROTECTED = {
    ("/api/v1/org", "get"),
    ("/api/v1/org", "patch"),
    ("/api/v1/org/members", "get"),
    ("/api/v1/org/invitations", "post"),
    ("/api/v1/org/members/{user_id}", "patch"),
    ("/api/v1/org/members/{user_id}", "delete"),
}
PUBLIC = {("/api/v1/org/invitations/{token}/accept", "post")}


async def load_spec() -> dict[str, Any]:
    async with AsyncClient(
        transport=ASGITransport(app=create_app(enable_docs=True)), base_url="http://test"
    ) as client:
        spec: dict[str, Any] = (await client.get("/api/v1/openapi.json")).json()
        return spec


async def test_organization_operations_are_documented() -> None:
    spec = await load_spec()
    valid_tags = {t["name"] for t in TAGS_METADATA}
    for path, method in PROTECTED | PUBLIC:
        op = spec["paths"][path][method]
        assert op["tags"] == ["organization"]
        assert op["summary"] and len(op["summary"]) < 60
        assert "**Roles:**" in op["description"], f"{method} {path} does not state who can call it"
        assert op["operationId"]
        assert set(op["tags"]) <= valid_tags
        assert "422" in op["responses"]
        assert "429" in op["responses"]


async def test_protected_routes_require_bearer_auth_and_document_401_and_403() -> None:
    spec = await load_spec()
    for path, method in PROTECTED:
        op = spec["paths"][path][method]
        assert {"BearerAuth": []} in op["security"], f"{method} {path} is not marked protected"
        assert {"401", "403"} <= set(op["responses"])


async def test_the_public_accept_route_declares_no_bearer_requirement() -> None:
    spec = await load_spec()
    op = spec["paths"]["/api/v1/org/invitations/{token}/accept"]["post"]
    assert "security" not in op
    assert {"401", "404", "409", "422"} <= set(op["responses"])


async def test_member_management_documents_the_last_admin_conflict() -> None:
    spec = await load_spec()
    for method in ("patch", "delete"):
        op = spec["paths"]["/api/v1/org/members/{user_id}"][method]
        assert {"404", "409"} <= set(op["responses"])


async def test_every_operation_id_stays_unique() -> None:
    spec = await load_spec()
    ids = [op["operationId"] for methods in spec["paths"].values() for op in methods.values()]
    assert len(ids) == len(set(ids))


async def test_the_invitation_token_is_not_part_of_any_response_schema() -> None:
    spec = await load_spec()
    props = spec["components"]["schemas"]["InvitationRead"]["properties"]
    assert set(props) == {"id", "email", "role", "expires_at", "created_at"}
