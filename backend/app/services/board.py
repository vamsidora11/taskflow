"""Boards and their columns. Audit hooks (board.created, board.updated, board.archived) arrive
with AuditService in Phase 5. Permission checks happen at the router."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

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
from app.services.auth import AuthenticatedUser

DEFAULT_COLUMNS = ["To Do", "In Progress", "Done"]


class BoardService:
    def __init__(self, session: AsyncSession, actor: AuthenticatedUser) -> None:
        self.session = session
        self.actor = actor
        self.boards = BoardRepository(session, actor.organization_id)
        self.columns = ColumnRepository(session, actor.organization_id)
        self.tasks = TaskRepository(session, actor.organization_id)

    async def create_board(
        self, *, name: str, description: str | None, columns: list[str] | None
    ) -> tuple[Board, list[BoardColumn]]:
        board = await self.boards.add(name=name, description=description, created_by=self.actor.id)
        created = [
            await self.columns.add(board_id=board.id, name=column_name, position=position)
            for position, column_name in enumerate(DEFAULT_COLUMNS if columns is None else columns)
        ]
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
        if name is not None:
            board.name = name
        if description_given:
            board.description = description
        if is_archived is not None:
            board.is_archived = is_archived
        await self.session.flush()
        await self.session.refresh(board)
        return board

    async def archive_board(self, board_id: uuid.UUID) -> None:
        """Idempotent: archiving an archived board succeeds."""
        board = await self.boards.lock(board_id)
        if board is None:
            raise BoardNotFoundError()
        board.is_archived = True
        await self.session.flush()

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
        return column

    async def update_column(
        self, column_id: uuid.UUID, *, name: str | None, position: int | None
    ) -> BoardColumn:
        column = await self._column_with_board_lock(column_id)
        if name is not None:
            column.name = name
        if position is not None:
            ordered = [
                c for c in await self.columns.list_for_board(column.board_id) if c.id != column.id
            ]
            ordered.insert(min(position, len(ordered)), column)
            await self.columns.apply_order(ordered)
        await self.session.flush()
        return column

    async def delete_column(self, column_id: uuid.UUID) -> None:
        column = await self._column_with_board_lock(column_id)
        if await self.tasks.count_active(column.id) > 0:
            raise ColumnNotEmptyError()
        board_id = column.board_id
        await self.session.delete(column)  # soft-deleted tasks go with it (ON DELETE CASCADE)
        await self.session.flush()
        remaining = await self.columns.list_for_board(board_id)
        await self.columns.apply_order(remaining)

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
