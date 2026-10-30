"""refresh tokens, RLS on organizations and users, pre-tenant lookup functions

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-30
"""

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ORG = "NULLIF(current_setting('app.current_org_id', true), '')::uuid"
_USER = "NULLIF(current_setting('app.current_user_id', true), '')::uuid"

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
        "refresh_tokens",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replaced_by_id", sa.Uuid(), nullable=True),
        sa.Column("user_agent", sa.String(500), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_refresh_tokens_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_refresh_tokens_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["replaced_by_id"],
            ["refresh_tokens.id"],
            name=op.f("fk_refresh_tokens_replaced_by_id_refresh_tokens"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_refresh_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_refresh_tokens_token_hash")),
    )
    op.create_index(op.f("ix_refresh_tokens_user_id"), "refresh_tokens", ["user_id"])
    op.create_index(op.f("ix_refresh_tokens_family_id"), "refresh_tokens", ["family_id"])

    app_role = _app_role()
    owner = _owner_role()

    # Sessions are never deleted by the API: revoked rows are what makes reuse detectable.
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON refresh_tokens TO {app_role}")

    # --- organizations: a session sees and writes only its active organization -------------
    op.execute("ALTER TABLE organizations ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE organizations FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON organizations "
        f"USING (id = {_ORG}) WITH CHECK (id = {_ORG})"
    )

    # --- users: global rows, visible to themselves and to members of the active org --------
    op.execute("ALTER TABLE users ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE users FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY users_select ON users FOR SELECT USING (id = {_USER} OR EXISTS ("
        f"SELECT 1 FROM memberships m WHERE m.user_id = users.id AND m.organization_id = {_ORG}))"
    )
    # Only a user's own row is ever writable, even by an admin of a shared organization.
    op.execute(f"CREATE POLICY users_insert ON users FOR INSERT WITH CHECK (id = {_USER})")
    op.execute(
        f"CREATE POLICY users_update ON users FOR UPDATE USING (id = {_USER}) "
        f"WITH CHECK (id = {_USER})"
    )
    op.execute(f"CREATE POLICY users_delete ON users FOR DELETE USING (id = {_USER})")

    # --- pre-tenant lookups ------------------------------------------------------------------
    # The functions below run as the table owner (SECURITY DEFINER). FORCE ROW LEVEL SECURITY
    # applies to the owner too, so it gets an explicit read policy. The runtime role is not the
    # owner and gets no such policy.
    for table in ("organizations", "users", "memberships"):
        op.execute(f"CREATE POLICY owner_read ON {table} FOR SELECT TO {owner} USING (true)")

    # Login: find an account by email before any session context exists.
    op.execute(
        """
        CREATE FUNCTION auth_find_user_by_email(p_email text)
        RETURNS TABLE (id uuid, email varchar, password_hash varchar, full_name varchar,
                       is_active boolean)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp
        AS $$
            SELECT u.id, u.email, u.password_hash, u.full_name, u.is_active
            FROM users u WHERE u.email = lower(p_email)
        $$
        """
    )
    # Memberships of the user in app.current_user_id, across organizations. It takes no argument
    # so a caller can only ever list its own memberships.
    op.execute(
        """
        CREATE FUNCTION auth_list_memberships()
        RETURNS TABLE (organization_id uuid, organization_name varchar,
                       organization_slug varchar, role varchar)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp
        AS $$
            SELECT m.organization_id, o.name, o.slug, m.role
            FROM memberships m JOIN organizations o ON o.id = m.organization_id
            WHERE m.user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
            ORDER BY m.created_at, m.id
        $$
        """
    )
    for fn in ("auth_find_user_by_email(text)", "auth_list_memberships()"):
        op.execute(f"REVOKE ALL ON FUNCTION {fn} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {fn} TO {app_role}")


def downgrade() -> None:
    op.execute("DROP FUNCTION auth_list_memberships()")
    op.execute("DROP FUNCTION auth_find_user_by_email(text)")
    for table in ("organizations", "users", "memberships"):
        op.execute(f"DROP POLICY owner_read ON {table}")
    for policy in ("users_select", "users_insert", "users_update", "users_delete"):
        op.execute(f"DROP POLICY {policy} ON users")
    op.execute("ALTER TABLE users NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE users DISABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY tenant_isolation ON organizations")
    op.execute("ALTER TABLE organizations NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE organizations DISABLE ROW LEVEL SECURITY")
    op.drop_index(op.f("ix_refresh_tokens_family_id"), table_name="refresh_tokens")
    op.drop_index(op.f("ix_refresh_tokens_user_id"), table_name="refresh_tokens")
    op.drop_table("refresh_tokens")
