from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class HealthStatus(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{"status": "ok"}]})

    status: Literal["ok"] = Field(description="Always `ok` when the process is serving requests.")


class ReadinessStatus(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"status": "ok", "checks": {"database": "ok", "redis": "ok"}}]
        }
    )

    status: Literal["ok", "unavailable"] = Field(
        description="`ok` when every dependency is reachable, otherwise `unavailable`."
    )
    checks: dict[str, Literal["ok", "error"]] = Field(
        description="Per-dependency state: `ok` or `error`."
    )
