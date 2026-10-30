import uuid
from datetime import datetime

from sqlalchemy import tuple_, update

from app.db.models.board import Board, BoardColumn
from app.repositories.base import TenantRepository


class BoardRepository(TenantRepository[Board]):
    model = Board

    async def lock(self, board_id: uuid.UUID) -> Board | None:
        """Row-lock a board. Every change to its columns or task order takes this lock first, so
        concurrent edits to one board are serialized and positions can never interleave."""
        stmt = self.scoped_select().where(Board.id == board_id).with_for_update()
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_page(
        self, *, include_archived: bool, limit: int, after: tuple[datetime, uuid.UUID] | None
    ) -> list[Board]:
        stmt = self.scoped_select().order_by(Board.created_at, Board.id).limit(limit)
        if not include_archived:
            stmt = stmt.where(Board.is_archived.is_(False))
        if after is not None:
            stmt = stmt.where(tuple_(Board.created_at, Board.id) > tuple_(*after))
        return list((await self.session.execute(stmt)).scalars().all())


class ColumnRepository(TenantRepository[BoardColumn]):
    model = BoardColumn

    async def list_for_board(self, board_id: uuid.UUID) -> list[BoardColumn]:
        stmt = (
            self.scoped_select()
            .where(BoardColumn.board_id == board_id)
            .order_by(BoardColumn.position)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_in_board(self, board_id: uuid.UUID, column_id: uuid.UUID) -> BoardColumn | None:
        stmt = self.scoped_select().where(
            BoardColumn.board_id == board_id, BoardColumn.id == column_id
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def apply_order(self, ordered: list[BoardColumn]) -> None:
        """Rewrite positions to 0..n-1 in the given order. The unique constraint is deferred, so
        intermediate duplicates inside the transaction are fine."""
        for position, column in enumerate(ordered):
            if column.position != position:
                await self.session.execute(
                    update(BoardColumn).where(BoardColumn.id == column.id).values(position=position)
                )
                column.position = position
