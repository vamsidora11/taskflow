"""comments and the append-only audit log

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-31
"""

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ORG = "NULLIF(current_setting('app.current_org_id', true), '')::uuid"
_ROLE_RE = re.compile(r"[a-z_][a-z0-9_]*")


def _app_role() -> str:
    role = op.get_context().config.get_main_option("app_role") or "app_user"  # type: ignore[union-attr]
    if not _ROLE_RE.fullmatch(role):
        raise ValueError(f"invalid app_role: {role!r}")
    return role


def upgrade() -> None:
    now = sa.func.now()
    op.create_table(
        "comments",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("author_id", sa.Uuid(), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_comments_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["tasks.id"], name=op.f("fk_comments_task_id_tasks"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["author_id"],
            ["users.id"],
            name=op.f("fk_comments_author_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_comments")),
    )
    op.create_index(op.f("ix_comments_organization_id"), "comments", ["organization_id"])
    op.create_index(op.f("ix_comments_task_id_created_at"), "comments", ["task_id", "created_at"])

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=True),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("entity_type", sa.String(32), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=False),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("request_id", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_audit_logs_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name=op.f("fk_audit_logs_actor_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_logs")),
    )
    op.create_index(
        op.f("ix_audit_logs_organization_id_created_at"),
        "audit_logs",
        ["organization_id", sa.text("created_at DESC")],
    )

    app_role = _app_role()
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON comments TO {app_role}")
    op.execute("ALTER TABLE comments ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE comments FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON comments "
        f"USING (organization_id = {_ORG}) WITH CHECK (organization_id = {_ORG})"
    )

    # Append-only: the runtime role may add and read rows, never change or remove them. There is
    # deliberately no UPDATE, DELETE or TRUNCATE grant, so even a bug or SQL injection in the API
    # cannot rewrite history.
    op.execute(f"GRANT SELECT, INSERT ON audit_logs TO {app_role}")
    op.execute("ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE audit_logs FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY audit_select ON audit_logs FOR SELECT USING (organization_id = {_ORG})"
    )
    # System events (no tenant) are writable but invisible to every tenant.
    op.execute(
        f"CREATE POLICY audit_insert ON audit_logs FOR INSERT "
        f"WITH CHECK (organization_id IS NULL OR organization_id = {_ORG})"
    )


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_table("comments")
