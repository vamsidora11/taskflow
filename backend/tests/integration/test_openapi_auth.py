from typing import Any

from httpx import ASGITransport, AsyncClient

from app.main import TAGS_METADATA, create_app

AUTH_PATHS = {
    ("/api/v1/auth/signup", "post"),
    ("/api/v1/auth/login", "post"),
    ("/api/v1/auth/refresh", "post"),
    ("/api/v1/auth/logout", "post"),
    ("/api/v1/auth/switch-org", "post"),
    ("/api/v1/auth/me", "get"),
}
PROTECTED = {("/api/v1/auth/switch-org", "post"), ("/api/v1/auth/me", "get")}


async def load_spec() -> dict[str, Any]:
    async with AsyncClient(
        transport=ASGITransport(app=create_app(enable_docs=True)), base_url="http://test"
    ) as client:
        spec: dict[str, Any] = (await client.get("/api/v1/openapi.json")).json()
        return spec


async def test_auth_operations_are_documented() -> None:
    spec = await load_spec()
    valid_tags = {t["name"] for t in TAGS_METADATA}
    for path, method in AUTH_PATHS:
        op = spec["paths"][path][method]
        assert op["summary"] and len(op["summary"]) < 60
        assert op["description"]
        assert op["operationId"]
        assert set(op["tags"]) <= valid_tags
        assert "422" in op["responses"] or op["responses"].keys() >= {"200"}


async def test_protected_auth_routes_declare_bearer_security_and_a_401() -> None:
    spec = await load_spec()
    for path, method in PROTECTED:
        op = spec["paths"][path][method]
        assert {"BearerAuth": []} in op["security"]
        assert "401" in op["responses"]
    public = spec["paths"]["/api/v1/auth/login"]["post"]
    assert "security" not in public


async def test_operation_ids_are_unique_and_bearer_scheme_is_declared() -> None:
    spec = await load_spec()
    ids = [op["operationId"] for methods in spec["paths"].values() for op in methods.values()]
    assert len(ids) == len(set(ids))
    assert spec["components"]["securitySchemes"]["BearerAuth"]["scheme"] == "bearer"


async def test_the_refresh_token_never_appears_in_a_response_schema() -> None:
    spec = await load_spec()
    token_props = spec["components"]["schemas"]["TokenResponse"]["properties"]
    assert "refresh_token" not in token_props
    assert "access_token" in token_props
