import uuid

from sqlalchemy import CheckConstraint, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.permissions import Role
from app.db.base import Base, CreatedAtMixin, TenantMixin, UUIDPrimaryKeyMixin

_ROLE_VALUES = ", ".join(f"'{r.value}'" for r in Role)


class Membership(UUIDPrimaryKeyMixin, CreatedAtMixin, TenantMixin, Base):
    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("organization_id", "user_id"),
        CheckConstraint(f"role IN ({_ROLE_VALUES})", name="role_valid"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
