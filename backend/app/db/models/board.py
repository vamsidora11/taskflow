import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    false,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin


class Board(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "boards"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_archived: Mapped[bool] = mapped_column(Boolean, server_default=false(), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class BoardColumn(UUIDPrimaryKeyMixin, CreatedAtMixin, TenantMixin, Base):
    """A status list on a board. Positions are dense (0..n-1) and renumbered on every change."""

    __tablename__ = "board_columns"
    __table_args__ = (
        # Deferred so a reorder can pass through duplicate positions inside one transaction.
        UniqueConstraint("board_id", "position", deferrable=True, initially="DEFERRED"),
        CheckConstraint("position >= 0", name="position_nonnegative"),
    )

    board_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("boards.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
