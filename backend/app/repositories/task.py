import uuid
from dataclasses import dataclass

from sqlalchemy import func, select, tuple_, update

from app.core.enums import Priority
from app.db.models.board import BoardColumn
from app.db.models.task import Task
from app.repositories.base import TenantRepository


@dataclass(frozen=True)
class TaskFilters:
    column_id: uuid.UUID | None = None
    assignee_id: uuid.UUID | None = None
    priority: Priority | None = None


@dataclass(frozen=True)
class TaskRow:
    task: Task
    column_position: int


class TaskRepository(TenantRepository[Task]):
    model = Task

    async def get_active(self, task_id: uuid.UUID) -> Task | None:
        stmt = self.scoped_select().where(Task.id == task_id, Task.deleted_at.is_(None))
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def count_active(
        self, column_id: uuid.UUID, *, excluding: uuid.UUID | None = None
    ) -> int:
        stmt = select(func.count(Task.id)).where(
            Task.organization_id == self.organization_id,
            Task.column_id == column_id,
            Task.deleted_at.is_(None),
        )
        if excluding is not None:
            stmt = stmt.where(Task.id != excluding)
        return int((await self.session.execute(stmt)).scalar_one())

    async def shift_positions(
        self,
        column_id: uuid.UUID,
        *,
        low: int,
        delta: int,
        high: int | None = None,
        excluding: uuid.UUID | None = None,
    ) -> None:
        """Add `delta` to the position of live tasks in `column_id` with low <= position <= high."""
        stmt = (
            update(Task)
            .where(
                Task.organization_id == self.organization_id,
                Task.column_id == column_id,
                Task.deleted_at.is_(None),
                Task.status_position >= low,
            )
            .values(status_position=Task.status_position + delta)
        )
        if high is not None:
            stmt = stmt.where(Task.status_position <= high)
        if excluding is not None:
            stmt = stmt.where(Task.id != excluding)
        await self.session.execute(stmt)

    async def list_page(
        self,
        board_id: uuid.UUID,
        filters: TaskFilters,
        *,
        limit: int,
        after: tuple[int, int, uuid.UUID] | None,
    ) -> list[TaskRow]:
        """Live tasks in board order: column position, then position within the column."""
        stmt = (
            select(Task, BoardColumn.position)
            .join(BoardColumn, BoardColumn.id == Task.column_id)
            .where(
                Task.organization_id == self.organization_id,
                Task.board_id == board_id,
                Task.deleted_at.is_(None),
            )
            .order_by(BoardColumn.position, Task.status_position, Task.id)
            .limit(limit)
        )
        if filters.column_id is not None:
            stmt = stmt.where(Task.column_id == filters.column_id)
        if filters.assignee_id is not None:
            stmt = stmt.where(Task.assignee_id == filters.assignee_id)
        if filters.priority is not None:
            stmt = stmt.where(Task.priority == filters.priority.value)
        if after is not None:
            stmt = stmt.where(
                tuple_(BoardColumn.position, Task.status_position, Task.id) > tuple_(*after)
            )
        return [TaskRow(task=r[0], column_position=r[1]) for r in await self.session.execute(stmt)]
