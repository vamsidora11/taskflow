import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.db.models.comment import Comment


class CommentCreate(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"examples": [{"body": "Looks good. Can we ship it Friday?"}]}
    )

    body: str = Field(min_length=1, max_length=5000, description="Markdown comment text.")


class CommentRead(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "id": "2b8f5d1c-6a3e-4f70-9c14-7d0e8a1b2c3d",
                    "task_id": "7c1d5e0a-3b2f-4a6d-8c9e-0f1a2b3c4d5e",
                    "author_id": "5d0c3b1e-7a52-4f5e-9d54-0c8f0a5e1a11",
                    "body": "Looks good. Can we ship it Friday?",
                    "created_at": "2026-10-31T09:00:00Z",
                    "updated_at": "2026-10-31T09:00:00Z",
                }
            ]
        }
    )

    id: uuid.UUID = Field(description="Comment id.")
    task_id: uuid.UUID = Field(description="Task the comment belongs to.")
    author_id: uuid.UUID | None = Field(description="Author; null if the account was deleted.")
    body: str = Field(description="Markdown comment text.")
    created_at: datetime = Field(description="Creation time (UTC).")
    updated_at: datetime = Field(description="Last change time (UTC).")

    @classmethod
    def from_comment(cls, comment: Comment) -> "CommentRead":
        return cls.model_validate(comment, from_attributes=True)
