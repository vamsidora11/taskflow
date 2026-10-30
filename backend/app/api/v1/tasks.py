import json
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, status

from app.api.deps import IdempotencyGuard, TenantSession, require_permission
from app.api.responses import FORBIDDEN, RATE_LIMITED, UNAUTHORIZED, VALIDATION, error
from app.core.enums import Priority
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from app.core.permissions import Permission
from app.repositories.task import TaskFilters
from app.schemas.common import Page
from app.schemas.task import TaskCreate, TaskMove, TaskRead, TaskUpdate
from app.services.auth import AuthenticatedUser
from app.services.idempotency import StoredResponse
from app.services.task import TaskService

router = APIRouter(prefix="/api/v1", tags=["tasks"])

BoardIdPath = Annotated[uuid.UUID, Path(description="Board id.")]
TaskIdPath = Annotated[uuid.UUID, Path(description="Task id.")]

_COMMON = {**UNAUTHORIZED, **FORBIDDEN, **VALIDATION, **RATE_LIMITED}
_NO_BOARD = error(404, "Board not found in the active organization")
_NO_TASK = error(404, "Task not found in the active organization")
_ARCHIVED = error(409, "The board is archived")
_OWNERSHIP = "Admins and managers can edit any task; a member can edit only tasks assigned to them."


@router.get(
    "/boards/{board_id}/tasks",
    response_model=Page[TaskRead],
    status_code=status.HTTP_200_OK,
    operation_id="list_tasks",
    summary="List the tasks on a board",
    description=(
        "Live tasks in board order (column, then position), with cursor pagination. Filters "
        "combine with AND.\n\n**Roles:** Admin, Manager, Member."
    ),
    responses={**_COMMON, **_NO_BOARD},
)
async def list_tasks(
    board_id: BoardIdPath,
    session: TenantSession,
    user: AuthenticatedUser = Depends(require_permission(Permission.TASK_VIEW)),
    column_id: uuid.UUID | None = Query(None, description="Only tasks in this column."),
    assignee_id: uuid.UUID | None = Query(None, description="Only tasks assigned to this user."),
    priority: Priority | None = Query(None, description="Only tasks with this priority."),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT, description="Page size."),
    cursor: str | None = Query(None, max_length=200, description="`next_cursor` of the last page."),
) -> Page[TaskRead]:
    rows, next_cursor = await TaskService(session, user).list_tasks(
        board_id,
        TaskFilters(column_id=column_id, assignee_id=assignee_id, priority=priority),
        limit=limit,
        cursor=cursor,
    )
    return Page[TaskRead](items=[TaskRead.from_task(r.task) for r in rows], next_cursor=next_cursor)


@router.post(
    "/boards/{board_id}/tasks",
    response_model=TaskRead,
    status_code=status.HTTP_201_CREATED,
    operation_id="create_task",
    summary="Create a task",
    description=(
        "Creates a task at the bottom of `column_id`, or of the board's first column.\n\n"
        "**Roles:** Admin, Manager, Member. A member may assign the task only to themselves "
        "or leave it unassigned.\n\n"
        "**Idempotency:** send the same `Idempotency-Key` within 24 hours to receive the "
        "original response (with `Idempotent-Replay: true`) instead of creating a duplicate. "
        "Reusing a key with a different body returns 409.\n\n"
        "**Audit:** will write `task.created` (Phase 5)."
    ),
    responses={
        **_COMMON,
        **_NO_BOARD,
        **error(
            409,
            "Board archived or without columns, or the Idempotency-Key was reused with a "
            "different request or is still in progress",
        ),
        **error(503, "Idempotency checks are unavailable (only when the header is sent)"),
    },
)
async def create_task(
    idempotency: IdempotencyGuard,  # first: its cleanup must run after the session commits
    board_id: BoardIdPath,
    payload: TaskCreate,
    session: TenantSession,
    user: AuthenticatedUser = Depends(require_permission(Permission.TASK_CREATE)),
) -> TaskRead:
    task = await TaskService(session, user).create_task(
        board_id,
        title=payload.title,
        description=payload.description,
        priority=payload.priority,
        assignee_id=payload.assignee_id,
        due_date=payload.due_date,
        column_id=payload.column_id,
    )
    result = TaskRead.from_task(task)
    if idempotency is not None:
        idempotency.result = StoredResponse(
            status=status.HTTP_201_CREATED, body=json.loads(result.model_dump_json())
        )
    return result


@router.get(
    "/tasks/{task_id}",
    response_model=TaskRead,
    status_code=status.HTTP_200_OK,
    operation_id="get_task",
    summary="Get a task",
    description="**Roles:** Admin, Manager, Member.",
    responses={**_COMMON, **_NO_TASK},
)
async def get_task(
    task_id: TaskIdPath,
    session: TenantSession,
    user: AuthenticatedUser = Depends(require_permission(Permission.TASK_VIEW)),
) -> TaskRead:
    return TaskRead.from_task(await TaskService(session, user).get_task(task_id))


@router.patch(
    "/tasks/{task_id}",
    response_model=TaskRead,
    status_code=status.HTTP_200_OK,
    operation_id="update_task",
    summary="Update a task",
    description=(
        f"Partial update; omitted fields are unchanged and `null` clears description, "
        f"assignee and due date. Use `POST /tasks/{{id}}/move` to change column or order.\n\n"
        f"**Roles:** {_OWNERSHIP} Only admins and managers can change the assignee.\n\n"
        "**Audit:** will write `task.updated` (Phase 5)."
    ),
    responses={**_COMMON, **_NO_TASK, **_ARCHIVED},
)
async def update_task(
    task_id: TaskIdPath,
    payload: TaskUpdate,
    session: TenantSession,
    user: AuthenticatedUser = Depends(require_permission(Permission.TASK_EDIT_OWN)),
) -> TaskRead:
    task = await TaskService(session, user).update_task(task_id, payload.changes())
    return TaskRead.from_task(task)


@router.delete(
    "/tasks/{task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="delete_task",
    summary="Delete a task",
    description=(
        "Soft-deletes the task: it disappears from every list and lookup, and the tasks below "
        "it move up.\n\n**Roles:** Admin, Manager.\n\n"
        "**Audit:** will write `task.deleted` (Phase 5)."
    ),
    responses={**_COMMON, **_NO_TASK, **_ARCHIVED},
)
async def delete_task(
    task_id: TaskIdPath,
    session: TenantSession,
    user: AuthenticatedUser = Depends(require_permission(Permission.TASK_DELETE)),
) -> None:
    await TaskService(session, user).delete_task(task_id)


@router.post(
    "/tasks/{task_id}/move",
    response_model=TaskRead,
    status_code=status.HTTP_200_OK,
    operation_id="move_task",
    summary="Move a task to a column and position",
    description=(
        "Moves the task to `column_id` at 0-based `position` (past the end means last). The "
        "source and target columns are renumbered in one transaction, so a move either fully "
        "happens or not at all.\n\n"
        f"**Roles:** {_OWNERSHIP}\n\n"
        "**Audit:** will write `task.moved` (Phase 5)."
    ),
    responses={
        **_COMMON,
        **error(404, "Task, or the target column on the task's board, not found"),
        **_ARCHIVED,
    },
)
async def move_task(
    task_id: TaskIdPath,
    payload: TaskMove,
    session: TenantSession,
    user: AuthenticatedUser = Depends(require_permission(Permission.TASK_EDIT_OWN)),
) -> TaskRead:
    task = await TaskService(session, user).move_task(
        task_id, column_id=payload.column_id, position=payload.position
    )
    return TaskRead.from_task(task)
