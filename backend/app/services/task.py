"""Tasks: creation, editing under ownership rules, atomic moves and soft delete.

Rules that live here rather than in the router (PLAN.md section 3):
  * Admins and managers may edit any task. A member may edit only tasks assigned to them.
  * Only admins and managers may (re)assign a task; a member may create a task only for
    themselves or unassigned.
  * A board is serialized by a row lock while its task order changes, and positions stay dense.
Audit hooks (task.created, task.updated, task.moved, task.deleted) arrive in Phase 5.
"""

import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import Priority
from app.core.exceptions import (
    BoardArchivedError,
    BoardHasNoColumnsError,
    BoardNotFoundError,
    ColumnNotFoundError,
    InvalidAssigneeError,
    InvalidCursorError,
    PermissionDeniedError,
    TaskNotFoundError,
)
from app.core.pagination import decode_keyset, encode_keyset
from app.core.permissions import Permission, has_permission
from app.db.models.board import Board
from app.db.models.task import Task
from app.repositories.board import BoardRepository, ColumnRepository
from app.repositories.membership import MembershipRepository
from app.repositories.task import TaskFilters, TaskRepository, TaskRow
from app.services.auth import AuthenticatedUser

EDITABLE_FIELDS = ("title", "description", "priority", "assignee_id", "due_date")


class TaskService:
    def __init__(self, session: AsyncSession, actor: AuthenticatedUser) -> None:
        self.session = session
        self.actor = actor
        org = actor.organization_id
        self.boards = BoardRepository(session, org)
        self.columns = ColumnRepository(session, org)
        self.tasks = TaskRepository(session, org)
        self.members = MembershipRepository(session, org)
        self.can_edit_any = has_permission(actor.role, Permission.TASK_EDIT_ANY)

    # --- reads ---------------------------------------------------------------------------

    async def list_tasks(
        self, board_id: uuid.UUID, filters: TaskFilters, *, limit: int, cursor: str | None
    ) -> tuple[list[TaskRow], str | None]:
        if await self.boards.get(board_id) is None:
            raise BoardNotFoundError()
        after = self._decode_cursor(cursor) if cursor else None
        rows = await self.tasks.list_page(board_id, filters, limit=limit + 1, after=after)
        page = rows[:limit]
        next_cursor = None
        if len(rows) > limit:
            last = page[-1]
            next_cursor = encode_keyset(
                last.column_position, last.task.status_position, str(last.task.id)
            )
        return page, next_cursor

    async def get_task(self, task_id: uuid.UUID) -> Task:
        task = await self.tasks.get_active(task_id)
        if task is None:
            raise TaskNotFoundError()
        return task

    # --- writes --------------------------------------------------------------------------

    async def create_task(
        self,
        board_id: uuid.UUID,
        *,
        title: str,
        description: str | None,
        priority: Priority,
        assignee_id: uuid.UUID | None,
        due_date: date | None,
        column_id: uuid.UUID | None,
    ) -> Task:
        await self._writable_board(board_id, lock=True)
        columns = await self.columns.list_for_board(board_id)
        if not columns:
            raise BoardHasNoColumnsError()
        if column_id is None:
            column = columns[0]
        else:
            column = next((c for c in columns if c.id == column_id), None)  # type: ignore[assignment]
            if column is None:
                raise ColumnNotFoundError()
        if assignee_id is not None:
            await self._check_assignee(assignee_id)
        position = await self.tasks.count_active(column.id)
        task = await self.tasks.add(
            board_id=board_id,
            column_id=column.id,
            title=title,
            description=description,
            priority=priority.value,
            status_position=position,
            assignee_id=assignee_id,
            due_date=due_date,
            created_by=self.actor.id,
        )
        await self.session.refresh(task)
        return task

    async def update_task(self, task_id: uuid.UUID, changes: dict[str, Any]) -> Task:
        task = await self.get_task(task_id)
        self._authorize_edit(task)
        await self._writable_board(task.board_id, lock=False)
        if "assignee_id" in changes and changes["assignee_id"] != task.assignee_id:
            if not self.can_edit_any:
                raise PermissionDeniedError("Only admins and managers can reassign tasks")
            if changes["assignee_id"] is not None:
                await self._check_assignee(changes["assignee_id"])
        for field in EDITABLE_FIELDS:
            if field in changes:
                value = changes[field]
                setattr(task, field, value.value if isinstance(value, Priority) else value)
        await self.session.flush()
        await self.session.refresh(task)
        return task

    async def delete_task(self, task_id: uuid.UUID) -> None:
        """Soft delete. Closes the gap so positions in the column stay dense."""
        task = await self.get_task(task_id)
        await self._writable_board(task.board_id, lock=True)
        await self.session.refresh(task)  # re-read under the lock
        if task.deleted_at is not None:
            raise TaskNotFoundError()
        await self.tasks.shift_positions(task.column_id, low=task.status_position + 1, delta=-1)
        task.deleted_at = datetime.now(UTC)
        await self.session.flush()

    async def move_task(self, task_id: uuid.UUID, *, column_id: uuid.UUID, position: int) -> Task:
        """Move to `column_id` at 0-based `position` (clamped to the end). One transaction, one
        board lock: either the whole reordering happens or none of it."""
        task = await self.get_task(task_id)
        self._authorize_edit(task)
        await self._writable_board(task.board_id, lock=True)
        await self.session.refresh(task)  # re-read under the lock
        if task.deleted_at is not None:
            raise TaskNotFoundError()
        target = await self.columns.get_in_board(task.board_id, column_id)
        if target is None:
            raise ColumnNotFoundError()

        source_id, old = task.column_id, task.status_position
        others = await self.tasks.count_active(target.id, excluding=task.id)
        new = max(0, min(position, others))

        if source_id == target.id:
            if new > old:  # moving down: tasks in (old, new] shift up by one
                await self.tasks.shift_positions(
                    source_id, low=old + 1, high=new, delta=-1, excluding=task.id
                )
            elif new < old:  # moving up: tasks in [new, old) shift down by one
                await self.tasks.shift_positions(
                    source_id, low=new, high=old - 1, delta=1, excluding=task.id
                )
        else:
            await self.tasks.shift_positions(source_id, low=old + 1, delta=-1, excluding=task.id)
            await self.tasks.shift_positions(target.id, low=new, delta=1, excluding=task.id)
        task.column_id = target.id
        task.status_position = new
        await self.session.flush()
        await self.session.refresh(task)
        return task

    # --- rules ---------------------------------------------------------------------------

    def _authorize_edit(self, task: Task) -> None:
        if self.can_edit_any or task.assignee_id == self.actor.id:
            return
        raise PermissionDeniedError("Members can only edit tasks assigned to them")

    async def _check_assignee(self, assignee_id: uuid.UUID) -> None:
        if not self.can_edit_any and assignee_id != self.actor.id:
            raise PermissionDeniedError("Only admins and managers can assign tasks to others")
        if await self.members.get_by_user_id(assignee_id) is None:
            raise InvalidAssigneeError()

    async def _writable_board(self, board_id: uuid.UUID, *, lock: bool) -> Board:
        board = await (self.boards.lock(board_id) if lock else self.boards.get(board_id))
        if board is None:
            raise BoardNotFoundError()
        if board.is_archived:
            raise BoardArchivedError()
        return board

    @staticmethod
    def _decode_cursor(cursor: str) -> tuple[int, int, uuid.UUID]:
        parts = decode_keyset(cursor, 3)
        try:
            col_pos, status_pos, task_id = parts
            if not isinstance(col_pos, int) or not isinstance(status_pos, int):
                raise ValueError("positions must be integers")
            return col_pos, status_pos, uuid.UUID(str(task_id))
        except ValueError as exc:
            raise InvalidCursorError() from exc
