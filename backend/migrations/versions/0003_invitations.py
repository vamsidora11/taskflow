"""invitations with row-level security and a pre-tenant token lookup

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-30
"""

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ORG = "NULLIF(current_setting('app.current_org_id', true), '')::uuid"
_ROLE_RE = re.compile(r"[a-z_][a-z0-9_]*")


def _app_role() -> str:
    role = op.get_context().config.get_main_option("app_role") or "app_user"  # type: ignore[union-attr]
    if not _ROLE_RE.fullmatch(role):
        raise ValueError(f"invalid app_role: {role!r}")
    return role


def _owner_role() -> str:
    owner = op.get_bind().execute(sa.text("SELECT current_user")).scalar_one()
    if not _ROLE_RE.fullmatch(owner):
        raise ValueError(f"invalid owner role: {owner!r}")
    return str(owner)


def upgrade() -> None:
    op.create_table(
        "invitations",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("invited_by", sa.Uuid(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "role IN ('admin', 'manager', 'member')", name=op.f("ck_invitations_role_valid")
        ),
        sa.CheckConstraint("email = lower(email)", name=op.f("ck_invitations_email_lowercase")),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_invitations_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["invited_by"],
            ["users.id"],
            name=op.f("fk_invitations_invited_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invitations")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_invitations_token_hash")),
    )
    op.create_index(op.f("ix_invitations_organization_id"), "invitations", ["organization_id"])

    app_role = _app_role()
    owner = _owner_role()

    # DELETE is granted so that re-inviting an address replaces its pending invitation.
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON invitations TO {app_role}")

    op.execute("ALTER TABLE invitations ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE invitations FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON invitations "
        f"USING (organization_id = {_ORG}) WITH CHECK (organization_id = {_ORG})"
    )
    # Read access for the SECURITY DEFINER lookup below, which runs as the table owner.
    op.execute(f"CREATE POLICY owner_read ON invitations FOR SELECT TO {owner} USING (true)")

    # Accepting an invitation starts from the emailed token, before any organization is known.
    # The 256-bit token (stored hashed) is the credential, and it identifies exactly one row.
    op.execute(
        """
        CREATE FUNCTION auth_find_invitation(p_token_hash text)
        RETURNS TABLE (id uuid, organization_id uuid, email varchar, role varchar,
                       expires_at timestamptz, accepted_at timestamptz)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp
        AS $$
            SELECT i.id, i.organization_id, i.email, i.role, i.expires_at, i.accepted_at
            FROM invitations i WHERE i.token_hash = p_token_hash
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION auth_find_invitation(text) FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION auth_find_invitation(text) TO {app_role}")


def downgrade() -> None:
    op.execute("DROP FUNCTION auth_find_invitation(text)")
    op.execute("DROP POLICY owner_read ON invitations")
    op.execute("DROP POLICY tenant_isolation ON invitations")
    op.drop_index(op.f("ix_invitations_organization_id"), table_name="invitations")
    op.drop_table("invitations")
