"""boards, board_columns and tasks with row-level security

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-30
"""

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ORG = "NULLIF(current_setting('app.current_org_id', true), '')::uuid"
_ROLE_RE = re.compile(r"[a-z_][a-z0-9_]*")
_NOW = sa.func.now()


def _app_role() -> str:
    role = op.get_context().config.get_main_option("app_role") or "app_user"  # type: ignore[union-attr]
    if not _ROLE_RE.fullmatch(role):
        raise ValueError(f"invalid app_role: {role!r}")
    return role


def _id() -> sa.Column[object]:
    return sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False)


def _ts(name: str) -> sa.Column[object]:
    return sa.Column(name, sa.DateTime(timezone=True), server_default=_NOW, nullable=False)


def _org_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["organization_id"],
        ["organizations.id"],
        name=op.f(f"fk_{table}_organization_id_organizations"),
        ondelete="CASCADE",
    )


def upgrade() -> None:
    op.create_table(
        "boards",
        _id(),
        _ts("created_at"),
        _ts("updated_at"),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_archived", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        _org_fk("boards"),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_boards_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_boards")),
    )
    op.create_index(op.f("ix_boards_organization_id"), "boards", ["organization_id"])

    op.create_table(
        "board_columns",
        _id(),
        _ts("created_at"),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("board_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.CheckConstraint("position >= 0", name=op.f("ck_board_columns_position_nonnegative")),
        _org_fk("board_columns"),
        sa.ForeignKeyConstraint(
            ["board_id"],
            ["boards.id"],
            name=op.f("fk_board_columns_board_id_boards"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_board_columns")),
        sa.UniqueConstraint(
            "board_id",
            "position",
            name=op.f("uq_board_columns_board_id_position"),
            deferrable=True,
            initially="DEFERRED",
        ),
    )
    op.create_index(op.f("ix_board_columns_organization_id"), "board_columns", ["organization_id"])
    op.create_index(op.f("ix_board_columns_board_id"), "board_columns", ["board_id"])

    op.create_table(
        "tasks",
        _id(),
        _ts("created_at"),
        _ts("updated_at"),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("board_id", sa.Uuid(), nullable=False),
        sa.Column("column_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("priority", sa.String(10), server_default="medium", nullable=False),
        sa.Column("status_position", sa.Integer(), nullable=False),
        sa.Column("assignee_id", sa.Uuid(), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "priority IN ('low', 'medium', 'high', 'urgent')", name=op.f("ck_tasks_priority_valid")
        ),
        sa.CheckConstraint(
            "status_position >= 0", name=op.f("ck_tasks_status_position_nonnegative")
        ),
        _org_fk("tasks"),
        sa.ForeignKeyConstraint(
            ["board_id"], ["boards.id"], name=op.f("fk_tasks_board_id_boards"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["column_id"],
            ["board_columns.id"],
            name=op.f("fk_tasks_column_id_board_columns"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["assignee_id"],
            ["users.id"],
            name=op.f("fk_tasks_assignee_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_tasks_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tasks")),
    )
    op.create_index(op.f("ix_tasks_organization_id"), "tasks", ["organization_id"])
    op.create_index(
        op.f("ix_tasks_organization_id_board_id"), "tasks", ["organization_id", "board_id"]
    )
    op.create_index(
        op.f("ix_tasks_organization_id_assignee_id"), "tasks", ["organization_id", "assignee_id"]
    )
    op.create_index(
        op.f("ix_tasks_column_id_status_position"), "tasks", ["column_id", "status_position"]
    )

    app_role = _app_role()
    for table in ("boards", "board_columns", "tasks"):
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO {app_role}")
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            f"USING (organization_id = {_ORG}) WITH CHECK (organization_id = {_ORG})"
        )


def downgrade() -> None:
    for table in ("tasks", "board_columns", "boards"):
        op.drop_table(table)  # policies, indexes and constraints go with the table
