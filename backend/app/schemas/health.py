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

    status: Literal["ok"] = Field(description="`ok` when all dependencies are reachable.")
    checks: dict[str, str] = Field(
        description="Per-dependency state: `ok`, or `not_configured` until probes exist."
    )
