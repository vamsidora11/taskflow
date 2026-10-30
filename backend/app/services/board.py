"""Boards and their columns. Audit hooks (board.created, board.updated, board.archived) arrive
with AuditService in Phase 5. Permission checks happen at the router."""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditAction
from app.core.exceptions import (
    BoardArchivedError,
    BoardNotFoundError,
    ColumnNotEmptyError,
    ColumnNotFoundError,
)
from app.core.pagination import decode_cursor, encode_cursor
from app.db.models.board import Board, BoardColumn
from app.repositories.board import BoardRepository, ColumnRepository
from app.repositories.task import TaskRepository
from app.services.audit import AuditService
from app.services.auth import AuthenticatedUser

DEFAULT_COLUMNS = ["To Do", "In Progress", "Done"]


class BoardService:
    def __init__(self, session: AsyncSession, actor: AuthenticatedUser) -> None:
        self.session = session
        self.actor = actor
        self.boards = BoardRepository(session, actor.organization_id)
        self.columns = ColumnRepository(session, actor.organization_id)
        self.tasks = TaskRepository(session, actor.organization_id)
        self.audit = AuditService(session)

    async def _audit(self, action: AuditAction, board_id: uuid.UUID, **kwargs: Any) -> None:
        await self.audit.record(
            action=action,
            entity_type="board",
            entity_id=board_id,
            organization_id=self.actor.organization_id,
            actor_user_id=self.actor.id,
            **kwargs,
        )

    async def create_board(
        self, *, name: str, description: str | None, columns: list[str] | None
    ) -> tuple[Board, list[BoardColumn]]:
        board = await self.boards.add(name=name, description=description, created_by=self.actor.id)
        created = [
            await self.columns.add(board_id=board.id, name=column_name, position=position)
            for position, column_name in enumerate(DEFAULT_COLUMNS if columns is None else columns)
        ]
        await self._audit(
            AuditAction.BOARD_CREATED,
            board.id,
            details={"name": name, "columns": [c.name for c in created]},
        )
        return board, created

    async def list_boards(
        self, *, include_archived: bool, limit: int, cursor: str | None
    ) -> tuple[list[Board], str | None]:
        after = decode_cursor(cursor) if cursor else None
        rows = await self.boards.list_page(
            include_archived=include_archived, limit=limit + 1, after=after
        )
        page = rows[:limit]
        next_cursor = encode_cursor(page[-1].created_at, page[-1].id) if len(rows) > limit else None
        return page, next_cursor

    async def get_board(self, board_id: uuid.UUID) -> tuple[Board, list[BoardColumn]]:
        board = await self.boards.get(board_id)
        if board is None:
            raise BoardNotFoundError()
        return board, await self.columns.list_for_board(board_id)

    async def update_board(
        self,
        board_id: uuid.UUID,
        *,
        name: str | None,
        description: str | None,
        description_given: bool,
        is_archived: bool | None,
    ) -> Board:
        board = await self.boards.lock(board_id)
        if board is None:
            raise BoardNotFoundError()
        before = {
            "name": board.name,
            "description": board.description,
            "is_archived": board.is_archived,
        }
        if name is not None:
            board.name = name
        if description_given:
            board.description = description
        if is_archived is not None:
            board.is_archived = is_archived
        await self.session.flush()
        await self.session.refresh(board)
        after = {
            "name": board.name,
            "description": board.description,
            "is_archived": board.is_archived,
        }
        if before != after:
            archived_now = after["is_archived"] and not before["is_archived"]
            await self._audit(
                AuditAction.BOARD_ARCHIVED if archived_now else AuditAction.BOARD_UPDATED,
                board.id,
                before=before,
                after=after,
            )
        return board

    async def archive_board(self, board_id: uuid.UUID) -> None:
        """Idempotent: archiving an archived board succeeds."""
        board = await self.boards.lock(board_id)
        if board is None:
            raise BoardNotFoundError()
        if not board.is_archived:
            board.is_archived = True
            await self.session.flush()
            await self._audit(
                AuditAction.BOARD_ARCHIVED,
                board.id,
                before={"is_archived": False},
                after={"is_archived": True},
            )

    # --- columns -------------------------------------------------------------------------

    async def add_column(
        self, board_id: uuid.UUID, *, name: str, position: int | None
    ) -> BoardColumn:
        await self._writable_board(board_id)
        existing = await self.columns.list_for_board(board_id)
        index = len(existing) if position is None else min(position, len(existing))
        column = await self.columns.add(board_id=board_id, name=name, position=len(existing))
        ordered = [c for c in existing]
        ordered.insert(index, column)
        await self.columns.apply_order(ordered)
        await self._audit(
            AuditAction.BOARD_UPDATED,
            board_id,
            details={"column": name, "operation": "added", "position": index},
        )
        return column

    async def update_column(
        self, column_id: uuid.UUID, *, name: str | None, position: int | None
    ) -> BoardColumn:
        column = await self._column_with_board_lock(column_id)
        old_name, old_position = column.name, column.position
        if name is not None:
            column.name = name
        if position is not None:
            ordered = [
                c for c in await self.columns.list_for_board(column.board_id) if c.id != column.id
            ]
            ordered.insert(min(position, len(ordered)), column)
            await self.columns.apply_order(ordered)
        await self.session.flush()
        if (old_name, old_position) != (column.name, column.position):
            await self._audit(
                AuditAction.BOARD_UPDATED,
                column.board_id,
                details={
                    "column": column.name,
                    "operation": "updated",
                    "changes": {
                        "name": [old_name, column.name],
                        "position": [old_position, column.position],
                    },
                },
            )
        return column

    async def delete_column(self, column_id: uuid.UUID) -> None:
        column = await self._column_with_board_lock(column_id)
        if await self.tasks.count_active(column.id) > 0:
            raise ColumnNotEmptyError()
        board_id, column_name = column.board_id, column.name
        await self.session.delete(column)  # soft-deleted tasks go with it (ON DELETE CASCADE)
        await self.session.flush()
        remaining = await self.columns.list_for_board(board_id)
        await self.columns.apply_order(remaining)
        await self._audit(
            AuditAction.BOARD_UPDATED,
            board_id,
            details={"column": column_name, "operation": "deleted"},
        )

    # --- helpers -------------------------------------------------------------------------

    async def _writable_board(self, board_id: uuid.UUID) -> Board:
        board = await self.boards.lock(board_id)
        if board is None:
            raise BoardNotFoundError()
        if board.is_archived:
            raise BoardArchivedError()
        return board

    async def _column_with_board_lock(self, column_id: uuid.UUID) -> BoardColumn:
        column = await self.columns.get(column_id)
        if column is None:
            raise ColumnNotFoundError()
        await self._writable_board(column.board_id)
        await self.session.refresh(column)  # positions may have moved while waiting for the lock
        return column
