import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, status

from app.api.deps import TenantSession, require_permission
from app.api.responses import FORBIDDEN, RATE_LIMITED, UNAUTHORIZED, VALIDATION, error
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from app.core.permissions import Permission
from app.schemas.comment import CommentCreate, CommentRead
from app.schemas.common import Page
from app.services.auth import AuthenticatedUser
from app.services.comment import CommentService

router = APIRouter(prefix="/api/v1", tags=["comments"])

TaskIdPath = Annotated[uuid.UUID, Path(description="Task id.")]
CommentIdPath = Annotated[uuid.UUID, Path(description="Comment id.")]

_COMMON = {**UNAUTHORIZED, **FORBIDDEN, **VALIDATION, **RATE_LIMITED}
_NO_TASK = error(404, "Task not found in the active organization")
_ARCHIVED = error(409, "The task's board is archived")


@router.get(
    "/tasks/{task_id}/comments",
    response_model=Page[CommentRead],
    status_code=status.HTTP_200_OK,
    operation_id="list_comments",
    summary="List a task's comments",
    description="Oldest first, with cursor pagination.\n\n**Roles:** Admin, Manager, Member.",
    responses={**_COMMON, **_NO_TASK},
)
async def list_comments(
    task_id: TaskIdPath,
    session: TenantSession,
    user: AuthenticatedUser = Depends(require_permission(Permission.TASK_VIEW)),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT, description="Page size."),
    cursor: str | None = Query(None, max_length=200, description="`next_cursor` of the last page."),
) -> Page[CommentRead]:
    rows, next_cursor = await CommentService(session, user).list_comments(
        task_id, limit=limit, cursor=cursor
    )
    return Page[CommentRead](
        items=[CommentRead.from_comment(c) for c in rows], next_cursor=next_cursor
    )


@router.post(
    "/tasks/{task_id}/comments",
    response_model=CommentRead,
    status_code=status.HTTP_201_CREATED,
    operation_id="create_comment",
    summary="Comment on a task",
    description=(
        "**Roles:** Admin, Manager, Member.\n\n**Audit:** writes a `comment.created` entry."
    ),
    responses={**_COMMON, **_NO_TASK, **_ARCHIVED},
)
async def create_comment(
    task_id: TaskIdPath,
    payload: CommentCreate,
    session: TenantSession,
    user: AuthenticatedUser = Depends(require_permission(Permission.COMMENT_CREATE)),
) -> CommentRead:
    comment = await CommentService(session, user).add_comment(task_id, body=payload.body)
    return CommentRead.from_comment(comment)


@router.delete(
    "/comments/{comment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="delete_comment",
    summary="Delete a comment",
    description=(
        "Soft-deletes the comment.\n\n**Roles:** the comment's author, or any Manager or Admin.\n\n"
        "**Audit:** writes a `comment.deleted` entry."
    ),
    responses={**_COMMON, **error(404, "Comment not found"), **_ARCHIVED},
)
async def delete_comment(
    comment_id: CommentIdPath,
    session: TenantSession,
    user: AuthenticatedUser = Depends(require_permission(Permission.COMMENT_CREATE)),
) -> None:
    await CommentService(session, user).delete_comment(comment_id)
