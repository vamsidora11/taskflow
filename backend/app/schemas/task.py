import uuid
from datetime import date, datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.enums import Priority
from app.db.models.task import Task

ASSIGNEE = "0b7c1f2e-9a3d-4c5b-8e7f-1a2b3c4d5e6f"


class TaskCreate(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "title": "Prepare Q4 board deck",
                    "description": "Include revenue forecast and hiring plan.",
                    "priority": "high",
                    "assignee_id": ASSIGNEE,
                    "due_date": "2026-11-15",
                }
            ]
        }
    )

    title: str = Field(min_length=1, max_length=200, description="Short task title.")
    description: str | None = Field(default=None, max_length=5000, description="Markdown body.")
    priority: Priority = Field(default=Priority.MEDIUM, description="Task priority.")
    assignee_id: uuid.UUID | None = Field(
        default=None, description="Must be a member of the same organization."
    )
    due_date: date | None = Field(default=None, description="ISO 8601 date (YYYY-MM-DD).")
    column_id: uuid.UUID | None = Field(
        default=None, description="Column to create the task in. Defaults to the first column."
    )


class TaskUpdate(BaseModel):
    """Partial update. Omitted fields are untouched; `null` clears description, assignee, date."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"title": "Prepare Q4 board deck v2", "priority": "urgent"}]
        }
    )

    title: str | None = Field(default=None, min_length=1, max_length=200, description="New title.")
    description: str | None = Field(default=None, max_length=5000, description="New body.")
    priority: Priority | None = Field(default=None, description="New priority.")
    assignee_id: uuid.UUID | None = Field(
        default=None, description="New assignee (admins and managers only); null unassigns."
    )
    due_date: date | None = Field(default=None, description="New due date; null clears it.")

    @model_validator(mode="after")
    def _required_fields_cannot_be_null(self) -> Self:
        for field in ("title", "priority"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self

    def changes(self) -> dict[str, object]:
        return {name: getattr(self, name) for name in self.model_fields_set}


class TaskMove(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"column_id": "9a1b2c3d-4e5f-4a6b-8c7d-0e1f2a3b4c5d", "position": 0}]
        }
    )

    column_id: uuid.UUID = Field(description="Target column. Must belong to the task's board.")
    position: int = Field(
        ge=0, description="0-based slot in the target column. Values past the end go last."
    )


class TaskRead(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "id": "7c1d5e0a-3b2f-4a6d-8c9e-0f1a2b3c4d5e",
                    "board_id": "3f2a8c1e-5b7d-4e9a-9d1f-2b3c4d5e6f70",
                    "column_id": "9a1b2c3d-4e5f-4a6b-8c7d-0e1f2a3b4c5d",
                    "title": "Prepare Q4 board deck",
                    "description": "Include revenue forecast and hiring plan.",
                    "priority": "high",
                    "position": 0,
                    "assignee_id": ASSIGNEE,
                    "due_date": "2026-11-15",
                    "created_by": "5d0c3b1e-7a52-4f5e-9d54-0c8f0a5e1a11",
                    "created_at": "2026-10-30T09:00:00Z",
                    "updated_at": "2026-10-30T09:00:00Z",
                }
            ]
        }
    )

    id: uuid.UUID = Field(description="Task id.")
    board_id: uuid.UUID = Field(description="Board the task is on.")
    column_id: uuid.UUID = Field(description="Column the task is in.")
    title: str = Field(description="Short task title.")
    description: str | None = Field(description="Markdown body.")
    priority: Priority = Field(description="Task priority.")
    position: int = Field(description="0-based order within the column.")
    assignee_id: uuid.UUID | None = Field(description="Assigned member, if any.")
    due_date: date | None = Field(description="Due date, if any.")
    created_by: uuid.UUID | None = Field(description="User who created the task.")
    created_at: datetime = Field(description="Creation time (UTC).")
    updated_at: datetime = Field(description="Last change time (UTC).")

    @classmethod
    def from_task(cls, task: Task) -> "TaskRead":
        return cls(
            id=task.id,
            board_id=task.board_id,
            column_id=task.column_id,
            title=task.title,
            description=task.description,
            priority=Priority(task.priority),
            position=task.status_position,
            assignee_id=task.assignee_id,
            due_date=task.due_date,
            created_by=task.created_by,
            created_at=task.created_at,
            updated_at=task.updated_at,
        )
