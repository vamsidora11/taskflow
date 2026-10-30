from pydantic import BaseModel, Field


class ErrorDetail(BaseModel):
    code: str = Field(
        description="Stable machine-readable code, e.g. TASK_NOT_FOUND",
        examples=["TASK_NOT_FOUND"],
    )
    message: str = Field(description="Human-readable message", examples=["Task not found"])
    request_id: str = Field(
        description="Correlates with server logs and audit rows", examples=["req_8f3a2c"]
    )


class ErrorResponse(BaseModel):
    error: ErrorDetail
