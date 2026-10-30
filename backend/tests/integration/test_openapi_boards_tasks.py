import json
from pathlib import Path
from typing import Any

from httpx import ASGITransport, AsyncClient

from app.main import TAGS_METADATA, create_app

PROTECTED = {
    "boards": [
        ("/api/v1/boards", "get"),
        ("/api/v1/boards", "post"),
        ("/api/v1/boards/{board_id}", "get"),
        ("/api/v1/boards/{board_id}", "patch"),
        ("/api/v1/boards/{board_id}", "delete"),
        ("/api/v1/boards/{board_id}/columns", "post"),
        ("/api/v1/columns/{column_id}", "patch"),
        ("/api/v1/columns/{column_id}", "delete"),
    ],
    "tasks": [
        ("/api/v1/boards/{board_id}/tasks", "get"),
        ("/api/v1/boards/{board_id}/tasks", "post"),
        ("/api/v1/tasks/{task_id}", "get"),
        ("/api/v1/tasks/{task_id}", "patch"),
        ("/api/v1/tasks/{task_id}", "delete"),
        ("/api/v1/tasks/{task_id}/move", "post"),
    ],
}


async def load_spec() -> dict[str, Any]:
    async with AsyncClient(
        transport=ASGITransport(app=create_app(enable_docs=True)), base_url="http://test"
    ) as client:
        spec: dict[str, Any] = (await client.get("/api/v1/openapi.json")).json()
        return spec


async def test_every_board_and_task_operation_is_fully_documented() -> None:
    spec = await load_spec()
    valid_tags = {t["name"] for t in TAGS_METADATA}
    for tag, operations in PROTECTED.items():
        for path, method in operations:
            op = spec["paths"][path][method]
            where = f"{method.upper()} {path}"
            assert op["tags"] == [tag], where
            assert op["summary"] and len(op["summary"]) < 60, where
            assert "**Roles:**" in op["description"], f"{where} does not say who can call it"
            assert op["operationId"], where
            assert set(op["tags"]) <= valid_tags, where
            assert {"BearerAuth": []} in op["security"], where
            assert {"401", "403", "422", "429"} <= set(op["responses"]), where


async def test_resource_routes_document_404_and_creates_declare_201() -> None:
    spec = await load_spec()
    for operations in PROTECTED.values():
        for path, method in operations:
            op = spec["paths"][path][method]
            if "{" in path:
                assert "404" in op["responses"], f"{method.upper()} {path}"
            if method == "post" and not path.endswith("/move"):
                assert "201" in op["responses"], f"{method.upper()} {path}"
            if method == "delete":
                assert "204" in op["responses"], f"{method.upper()} {path}"


async def test_create_task_documents_the_idempotency_header_and_its_errors() -> None:
    op = (await load_spec())["paths"]["/api/v1/boards/{board_id}/tasks"]["post"]
    header = next(p for p in op["parameters"] if p["name"] == "Idempotency-Key")
    assert header["in"] == "header"
    string_schema = next(a for a in header["schema"]["anyOf"] if a.get("type") == "string")
    assert string_schema["maxLength"] == 128
    assert header["description"]
    assert {"409", "503"} <= set(op["responses"])
    assert "Idempotent-Replay" in op["description"]


async def test_task_list_documents_its_filters() -> None:
    op = (await load_spec())["paths"]["/api/v1/boards/{board_id}/tasks"]["get"]
    params = {p["name"]: p for p in op["parameters"]}
    assert {"column_id", "assignee_id", "priority", "cursor", "limit"} <= set(params)
    assert all(p.get("description") for p in params.values())


async def test_every_schema_field_has_a_description_and_examples_validate() -> None:
    from app.schemas.board import BoardCreate, BoardUpdate, ColumnCreate, ColumnUpdate
    from app.schemas.task import TaskCreate, TaskMove, TaskUpdate

    spec = await load_spec()
    for name in (
        "BoardCreate",
        "BoardUpdate",
        "BoardRead",
        "BoardDetail",
        "ColumnCreate",
        "ColumnUpdate",
        "ColumnRead",
        "TaskCreate",
        "TaskUpdate",
        "TaskMove",
        "TaskRead",
    ):
        for field, schema in spec["components"]["schemas"][name]["properties"].items():
            assert schema.get("description"), f"{name}.{field} has no description"
    for model in (
        BoardCreate,
        BoardUpdate,
        ColumnCreate,
        ColumnUpdate,
        TaskCreate,
        TaskUpdate,
        TaskMove,
    ):
        for example in model.model_json_schema()["examples"]:
            model.model_validate(example)


async def test_operation_ids_are_unique_and_the_committed_spec_is_current() -> None:
    spec = await load_spec()
    ids = [op["operationId"] for methods in spec["paths"].values() for op in methods.values()]
    assert len(ids) == len(set(ids))


def test_docs_openapi_json_matches_the_app() -> None:
    """The committed spec is the public contract. If this fails, regenerate it:
    `cd backend && python -m scripts.export_openapi`."""
    committed = Path(__file__).resolve().parents[3] / "docs" / "openapi.json"
    app = create_app(enable_docs=True)
    expected = json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"
    assert committed.read_text(encoding="utf-8").replace("\r\n", "\n") == expected
