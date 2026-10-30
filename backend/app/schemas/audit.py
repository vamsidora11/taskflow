import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.db.models.audit_log import AuditLog


class AuditLogRead(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "id": 1042,
                    "action": "task.updated",
                    "entity_type": "task",
                    "entity_id": "7c1d5e0a-3b2f-4a6d-8c9e-0f1a2b3c4d5e",
                    "actor_user_id": "5d0c3b1e-7a52-4f5e-9d54-0c8f0a5e1a11",
                    "metadata": {"changes": {"priority": {"from": "medium", "to": "urgent"}}},
                    "ip_address": "203.0.113.7",
                    "request_id": "req_8f3a2c",
                    "created_at": "2026-10-31T09:00:00Z",
                }
            ]
        }
    )

    id: int = Field(description="Monotonic id; newer entries have larger ids.")
    action: str = Field(description="What happened, e.g. `task.updated`.")
    entity_type: str = Field(description="Kind of thing it happened to, e.g. `task`.")
    entity_id: uuid.UUID | None = Field(description="Id of that thing, when there is one.")
    actor_user_id: uuid.UUID | None = Field(description="Who did it; null for system events.")
    metadata: dict[str, Any] = Field(
        description="Changed fields as `{field: {from, to}}` under `changes`, plus event details."
    )
    ip_address: str | None = Field(description="Client address of the request.")
    request_id: str | None = Field(description="Matches `X-Request-ID` and the server logs.")
    created_at: datetime = Field(description="When it happened (UTC).")

    @classmethod
    def from_log(cls, log: AuditLog) -> "AuditLogRead":
        return cls(
            id=log.id,
            action=log.action,
            entity_type=log.entity_type,
            entity_id=log.entity_id,
            actor_user_id=log.actor_user_id,
            metadata=log.meta,
            ip_address=log.ip_address,
            request_id=log.request_id,
            created_at=log.created_at,
        )
