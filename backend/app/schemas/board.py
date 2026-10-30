import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.db.models.board import Board, BoardColumn

BOARD_ID = "3f2a8c1e-5b7d-4e9a-9d1f-2b3c4d5e6f70"

ColumnName = Annotated[str, StringConstraints(min_length=1, max_length=100)]


class BoardCreate(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "name": "Q4 Launch",
                    "description": "Everything needed for the Q4 release.",
                    "columns": ["Backlog", "In Progress", "Review", "Done"],
                }
            ]
        }
    )

    name: str = Field(min_length=1, max_length=200, description="Board name.")
    description: str | None = Field(default=None, max_length=2000, description="Markdown body.")
    columns: list[ColumnName] | None = Field(
        default=None,
        max_length=20,
        description="Column names, left to right. Defaults to To Do, In Progress, Done.",
    )


class BoardUpdate(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"examples": [{"name": "Q4 Launch (final)", "is_archived": False}]}
    )

    name: str | None = Field(default=None, min_length=1, max_length=200, description="New name.")
    description: str | None = Field(
        default=None, max_length=2000, description="New description; send null to clear it."
    )
    is_archived: bool | None = Field(
        default=None, description="Archive or restore the board. Archiving is also DELETE."
    )


class BoardRead(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "id": BOARD_ID,
                    "name": "Q4 Launch",
                    "description": "Everything needed for the Q4 release.",
                    "is_archived": False,
                    "created_by": "5d0c3b1e-7a52-4f5e-9d54-0c8f0a5e1a11",
                    "created_at": "2026-10-30T09:00:00Z",
                    "updated_at": "2026-10-30T09:00:00Z",
                }
            ]
        }
    )

    id: uuid.UUID = Field(description="Board id.")
    name: str = Field(description="Board name.")
    description: str | None = Field(description="Markdown body.")
    is_archived: bool = Field(description="Archived boards are read-only and hidden by default.")
    created_by: uuid.UUID | None = Field(description="User who created the board.")
    created_at: datetime = Field(description="Creation time (UTC).")
    updated_at: datetime = Field(description="Last change time (UTC).")

    @classmethod
    def from_board(cls, board: Board) -> "BoardRead":
        return cls.model_validate(board, from_attributes=True)


class ColumnRead(BaseModel):
    id: uuid.UUID = Field(description="Column id.")
    board_id: uuid.UUID = Field(description="Board the column belongs to.")
    name: str = Field(description="Column name.")
    position: int = Field(description="0-based order from left to right.")
    created_at: datetime = Field(description="Creation time (UTC).")

    @classmethod
    def from_column(cls, column: BoardColumn) -> "ColumnRead":
        return cls.model_validate(column, from_attributes=True)


class BoardDetail(BoardRead):
    columns: list[ColumnRead] = Field(description="The board's columns in order.")

    @classmethod
    def build(cls, board: Board, columns: list[BoardColumn]) -> "BoardDetail":
        data = BoardRead.from_board(board).model_dump()
        return cls(**data, columns=[ColumnRead.from_column(c) for c in columns])


class ColumnCreate(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{"name": "Blocked", "position": 2}]})

    name: str = Field(min_length=1, max_length=100, description="Column name.")
    position: int | None = Field(
        default=None, ge=0, description="0-based slot to insert at. Defaults to the far right."
    )


class ColumnUpdate(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{"name": "Blocked", "position": 0}]})

    name: str | None = Field(default=None, min_length=1, max_length=100, description="New name.")
    position: int | None = Field(
        default=None, ge=0, description="New 0-based slot. Other columns shift to make room."
    )
