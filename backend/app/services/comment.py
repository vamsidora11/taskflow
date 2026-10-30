"""Comments on tasks. A member may delete their own comments; managers and admins any."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditAction
from app.core.exceptions import (
    BoardArchivedError,
    BoardNotFoundError,
    CommentNotFoundError,
    PermissionDeniedError,
    TaskNotFoundError,
)
from app.core.pagination import decode_cursor, encode_cursor
from app.core.permissions import Permission, has_permission
from app.db.models.comment import Comment
from app.repositories.base import TenantRepository
from app.repositories.board import BoardRepository
from app.repositories.task import TaskRepository
from app.services.audit import AuditService
from app.services.auth import AuthenticatedUser


class CommentRepository(TenantRepository[Comment]):
    model = Comment

    async def get_active(self, comment_id: uuid.UUID) -> Comment | None:
        stmt = self.scoped_select().where(Comment.id == comment_id, Comment.deleted_at.is_(None))
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_page(
        self, task_id: uuid.UUID, *, limit: int, after: tuple[datetime, uuid.UUID] | None
    ) -> list[Comment]:
        stmt = (
            self.scoped_select()
            .where(Comment.task_id == task_id, Comment.deleted_at.is_(None))
            .order_by(Comment.created_at, Comment.id)
            .limit(limit)
        )
        if after is not None:
            stmt = stmt.where(tuple_(Comment.created_at, Comment.id) > tuple_(*after))
        return list((await self.session.execute(stmt)).scalars().all())


class CommentService:
    def __init__(self, session: AsyncSession, actor: AuthenticatedUser) -> None:
        self.session = session
        self.actor = actor
        org = actor.organization_id
        self.comments = CommentRepository(session, org)
        self.tasks = TaskRepository(session, org)
        self.boards = BoardRepository(session, org)
        self.audit = AuditService(session)

    async def _task(self, task_id: uuid.UUID, *, writable: bool) -> None:
        task = await self.tasks.get_active(task_id)
        if task is None:
            raise TaskNotFoundError()
        if writable:
            board = await self.boards.get(task.board_id)
            if board is None:
                raise BoardNotFoundError()
            if board.is_archived:
                raise BoardArchivedError()

    async def list_comments(
        self, task_id: uuid.UUID, *, limit: int, cursor: str | None
    ) -> tuple[list[Comment], str | None]:
        await self._task(task_id, writable=False)
        after = decode_cursor(cursor) if cursor else None
        rows = await self.comments.list_page(task_id, limit=limit + 1, after=after)
        page = rows[:limit]
        next_cursor = encode_cursor(page[-1].created_at, page[-1].id) if len(rows) > limit else None
        return page, next_cursor

    async def add_comment(self, task_id: uuid.UUID, *, body: str) -> Comment:
        await self._task(task_id, writable=True)
        comment = await self.comments.add(task_id=task_id, author_id=self.actor.id, body=body)
        await self.session.refresh(comment)
        await self.audit.record(
            action=AuditAction.COMMENT_CREATED,
            entity_type="comment",
            entity_id=comment.id,
            organization_id=self.actor.organization_id,
            actor_user_id=self.actor.id,
            details={"task_id": task_id},
        )
        return comment

    async def delete_comment(self, comment_id: uuid.UUID) -> None:
        comment = await self.comments.get_active(comment_id)
        if comment is None:
            raise CommentNotFoundError()
        is_author = comment.author_id == self.actor.id
        if not is_author and not has_permission(self.actor.role, Permission.COMMENT_DELETE_ANY):
            raise PermissionDeniedError("Only the author, a manager or an admin can delete this")
        await self._task(comment.task_id, writable=True)
        comment.deleted_at = datetime.now(UTC)
        await self.session.flush()
        await self.audit.record(
            action=AuditAction.COMMENT_DELETED,
            entity_type="comment",
            entity_id=comment.id,
            organization_id=self.actor.organization_id,
            actor_user_id=self.actor.id,
            details={"task_id": comment.task_id, "by_author": is_author},
        )
