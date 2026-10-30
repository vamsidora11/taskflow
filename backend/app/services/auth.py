"""Authentication business rules. No FastAPI imports; the router owns cookies and HTTP.

Transactions: unlike tenant-scoped request sessions, these methods commit explicitly. Refresh
reuse detection must persist the family revocation *before* raising the 401, which a
rollback-on-error session would undo. Audit hooks (auth.login, auth.login_failed,
auth.refresh_reuse_detected) arrive with AuditService in Phase 5.
"""

import hashlib
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditAction
from app.core.config import settings
from app.core.exceptions import (
    EmailAlreadyRegisteredError,
    InvalidCredentialsError,
    InvalidRefreshTokenError,
    InvalidTokenError,
    NoOrganizationError,
    OrganizationNotFoundError,
)
from app.core.permissions import Role
from app.core.security import (
    DUMMY_PASSWORD_HASH,
    AccessTokenClaims,
    create_access_token,
    hash_password,
    hash_refresh_token,
    new_refresh_token,
    verify_password,
)
from app.db.models.refresh_token import RefreshToken
from app.db.session import set_context
from app.repositories.identity import IdentityRepository, OrganizationMembershipRecord
from app.repositories.membership import MembershipRepository
from app.repositories.organization import OrganizationRepository
from app.repositories.refresh_token import RefreshTokenRepository
from app.repositories.user import UserRepository
from app.services.audit import AuditService


@dataclass(frozen=True)
class ClientInfo:
    user_agent: str | None = None
    ip_address: str | None = None


@dataclass(frozen=True)
class AuthTokens:
    access_token: str
    expires_in: int
    refresh_token: str
    refresh_expires_at: datetime
    organization_id: uuid.UUID
    role: str


@dataclass(frozen=True)
class AuthenticatedUser:
    id: uuid.UUID
    email: str
    full_name: str
    organization_id: uuid.UUID
    role: str


@dataclass(frozen=True)
class AccountOverview:
    user: AuthenticatedUser
    organizations: list[OrganizationMembershipRecord]


def slugify(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60] or "org"
    return f"{base}-{uuid.uuid4().hex[:6]}"


async def resolve_authenticated_user(
    session: AsyncSession, claims: AccessTokenClaims
) -> AuthenticatedUser:
    """Re-check the token against the database on every request.

    The session must already be scoped to the token's organization and user. A user who was
    removed or deactivated gets the same generic error as a bad signature, and the role comes
    from the live membership rather than the token claim.
    """
    membership = await MembershipRepository(session, claims.org_id).get_by_user_id(claims.user_id)
    user = await UserRepository(session).get(claims.user_id)
    if membership is None or user is None or not user.is_active:
        raise InvalidTokenError()
    return AuthenticatedUser(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        organization_id=claims.org_id,
        role=membership.role,
    )


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.identity = IdentityRepository(session)
        self.users = UserRepository(session)
        self.orgs = OrganizationRepository(session)
        self.tokens = RefreshTokenRepository(session)
        self.audit = AuditService(session)

    async def signup(
        self,
        *,
        organization_name: str,
        email: str,
        password: str,
        full_name: str,
        client: ClientInfo,
    ) -> AuthTokens:
        email = email.lower()
        if await self.identity.find_user_by_email(email) is not None:
            raise EmailAlreadyRegisteredError()

        org_id, user_id = uuid.uuid4(), uuid.uuid4()
        # Both identities are known up front, so RLS admits exactly these new rows and no others.
        await set_context(self.session, org_id=org_id, user_id=user_id)
        try:
            await self.orgs.add(
                org_id=org_id, name=organization_name, slug=slugify(organization_name)
            )
            await self.users.add(
                user_id=user_id,
                email=email,
                password_hash=hash_password(password),
                full_name=full_name,
            )
            await MembershipRepository(self.session, org_id).add(
                user_id=user_id, role=Role.ADMIN.value
            )
            tokens, _ = await self.issue_session(user_id, org_id, Role.ADMIN.value, None, client)
            await self.audit.record(
                action=AuditAction.ORG_CREATED,
                entity_type="organization",
                entity_id=org_id,
                organization_id=org_id,
                actor_user_id=user_id,
                details={"name": organization_name},
            )
            await self.audit.record(
                action=AuditAction.AUTH_LOGIN,
                entity_type="user",
                entity_id=user_id,
                organization_id=org_id,
                actor_user_id=user_id,
                details={"method": "signup"},
            )
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            if "uq_users_email" in str(exc.orig):  # lost a race with a concurrent signup
                raise EmailAlreadyRegisteredError() from exc
            raise
        return tokens

    async def login(self, *, email: str, password: str, client: ClientInfo) -> AuthTokens:
        user = await self.identity.find_user_by_email(email.lower())
        # Always run one Argon2 verification so response time does not reveal whether the
        # account exists; unknown email, wrong password and disabled account look identical.
        password_ok = verify_password(password, user.password_hash if user else DUMMY_PASSWORD_HASH)
        if user is None or not password_ok or not user.is_active:
            # A system event (no tenant): stored, but hidden from every organization. The
            # attempted address is kept only as a short fingerprint, since people sometimes type
            # their password into the email box. Committed here because the error rolls back.
            await self.audit.record(
                action=AuditAction.AUTH_LOGIN_FAILED,
                entity_type="user",
                entity_id=user.id if user else None,
                organization_id=None,
                actor_user_id=user.id if user else None,
                details={
                    "reason": "invalid_credentials",
                    "email_fingerprint": hashlib.sha256(email.lower().encode()).hexdigest()[:12],
                },
            )
            await self.session.commit()
            raise InvalidCredentialsError()

        await set_context(self.session, user_id=user.id)
        memberships = await self.identity.list_memberships()
        if not memberships:
            raise NoOrganizationError()
        active = memberships[0]  # earliest membership; POST /auth/switch-org changes it

        await set_context(self.session, org_id=active.organization_id)
        tokens, _ = await self.issue_session(
            user.id, active.organization_id, active.role, None, client
        )
        await self.audit.record(
            action=AuditAction.AUTH_LOGIN,
            entity_type="user",
            entity_id=user.id,
            organization_id=active.organization_id,
            actor_user_id=user.id,
            details={"method": "password"},
        )
        await self.session.commit()
        return tokens

    async def refresh(self, *, refresh_token: str | None, client: ClientInfo) -> AuthTokens:
        if not refresh_token:
            raise InvalidRefreshTokenError()
        row = await self.tokens.get_by_hash_for_update(hash_refresh_token(refresh_token))
        if row is None:
            raise InvalidRefreshTokenError()

        now = datetime.now(UTC)
        if row.revoked_at is not None or row.replaced_by_id is not None:
            # A rotated or revoked token came back: assume it was stolen. Kill the whole family
            # and commit before raising, or the revocation would be rolled back with the error.
            await self.tokens.revoke_family(row.family_id, now)
            await set_context(self.session, org_id=row.organization_id, user_id=row.user_id)
            await self.audit.record(
                action=AuditAction.AUTH_REFRESH_REUSE,
                entity_type="user",
                entity_id=row.user_id,
                organization_id=row.organization_id,
                actor_user_id=row.user_id,
                details={"family_id": row.family_id},
            )
            await self.session.commit()
            raise InvalidRefreshTokenError()
        if row.expires_at <= now:
            raise InvalidRefreshTokenError()

        await set_context(self.session, org_id=row.organization_id, user_id=row.user_id)
        membership = await MembershipRepository(self.session, row.organization_id).get_by_user_id(
            row.user_id
        )
        user = await self.users.get(row.user_id)
        if membership is None or user is None or not user.is_active:
            await self.tokens.revoke_family(row.family_id, now)
            await self.session.commit()
            raise InvalidRefreshTokenError()

        tokens, new_row = await self.issue_session(
            row.user_id, row.organization_id, membership.role, row.family_id, client
        )
        row.replaced_by_id = new_row.id
        await self.session.commit()
        return tokens

    async def logout(self, *, refresh_token: str | None) -> None:
        if not refresh_token:
            return
        row = await self.tokens.get_by_hash_for_update(hash_refresh_token(refresh_token))
        if row is not None:
            await self.tokens.revoke_family(row.family_id, datetime.now(UTC))
            await self.session.commit()

    async def switch_organization(
        self,
        *,
        user_id: uuid.UUID,
        target_org_id: uuid.UUID,
        current_refresh_token: str | None,
        client: ClientInfo,
    ) -> AuthTokens:
        await set_context(self.session, org_id=target_org_id, user_id=user_id)
        membership = await MembershipRepository(self.session, target_org_id).get_by_user_id(user_id)
        if membership is None:
            # Same answer whether the organization exists or not.
            raise OrganizationNotFoundError()

        if current_refresh_token:
            old = await self.tokens.get_by_hash_for_update(
                hash_refresh_token(current_refresh_token)
            )
            if old is not None and old.user_id == user_id:
                await self.tokens.revoke_family(old.family_id, datetime.now(UTC))
        tokens, _ = await self.issue_session(user_id, target_org_id, membership.role, None, client)
        await self.session.commit()
        return tokens

    async def account_overview(self, user: AuthenticatedUser) -> AccountOverview:
        return AccountOverview(user=user, organizations=await self.identity.list_memberships())

    async def issue_session(
        self,
        user_id: uuid.UUID,
        org_id: uuid.UUID,
        role: str,
        family_id: uuid.UUID | None,
        client: ClientInfo,
    ) -> tuple[AuthTokens, RefreshToken]:
        raw = new_refresh_token()
        expires_at = datetime.now(UTC) + timedelta(days=settings.refresh_token_ttl_days)
        row = await self.tokens.add(
            user_id=user_id,
            organization_id=org_id,
            token_hash=hash_refresh_token(raw),
            family_id=family_id or uuid.uuid4(),
            expires_at=expires_at,
            user_agent=client.user_agent[:500] if client.user_agent else None,
            ip_address=client.ip_address,
        )
        access_token, expires_in = create_access_token(user_id, org_id, role)
        tokens = AuthTokens(
            access_token=access_token,
            expires_in=expires_in,
            refresh_token=raw,
            refresh_expires_at=expires_at,
            organization_id=org_id,
            role=role,
        )
        return tokens, row
