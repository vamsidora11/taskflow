import uuid
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import Priority
from app.db.base import Base, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin

_PRIORITY_VALUES = ", ".join(f"'{p.value}'" for p in Priority)


class Task(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    """A card on a board. `status_position` is its dense 0-based order within its column among
    live tasks; soft-deleted tasks keep a stale value and are ignored by every position query."""

    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint(f"priority IN ({_PRIORITY_VALUES})", name="priority_valid"),
        CheckConstraint("status_position >= 0", name="status_position_nonnegative"),
        Index("ix_tasks_organization_id_board_id", "organization_id", "board_id"),
        Index("ix_tasks_organization_id_assignee_id", "organization_id", "assignee_id"),
        Index("ix_tasks_column_id_status_position", "column_id", "status_position"),
    )

    board_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("boards.id", ondelete="CASCADE"), nullable=False
    )
    column_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("board_columns.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    priority: Mapped[str] = mapped_column(String(10), nullable=False, server_default="medium")
    status_position: Mapped[int] = mapped_column(Integer, nullable=False)
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
