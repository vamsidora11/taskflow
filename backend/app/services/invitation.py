"""Inviting people to an organization and accepting those invitations.

Audit hooks (member.invited, member.joined) arrive with AuditService in Phase 5.
"""

import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import (
    AlreadyMemberError,
    EmailAlreadyRegisteredError,
    InvalidCredentialsError,
    InvitationNotFoundError,
    OrganizationNotFoundError,
    ValidationFailedError,
)
from app.core.permissions import Role
from app.core.security import MIN_PASSWORD_LENGTH, hash_password, hash_token, verify_password
from app.db.models.invitation import Invitation
from app.db.session import set_context
from app.repositories.identity import IdentityRepository
from app.repositories.invitation import InvitationRepository
from app.repositories.membership import MembershipRepository
from app.repositories.organization import OrganizationRepository
from app.repositories.user import UserRepository
from app.services.auth import AuthenticatedUser, AuthService, AuthTokens, ClientInfo
from app.services.email import EmailMessage


@dataclass(frozen=True)
class IssuedInvitation:
    invitation: Invitation
    email: EmailMessage  # send only after the transaction has committed


class InvitationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.identity = IdentityRepository(session)

    async def invite(self, *, actor: AuthenticatedUser, email: str, role: Role) -> IssuedInvitation:
        """Create an invitation inside the caller's tenant-scoped transaction."""
        email = email.lower()
        org = await OrganizationRepository(self.session).get(actor.organization_id)
        if org is None:
            raise OrganizationNotFoundError()

        existing = await self.identity.find_user_by_email(email)
        if existing is not None:
            members = MembershipRepository(self.session, actor.organization_id)
            if await members.get_by_user_id(existing.id) is not None:
                raise AlreadyMemberError()

        invitations = InvitationRepository(self.session, actor.organization_id)
        await invitations.delete_pending_for_email(email)
        token = secrets.token_urlsafe(32)
        invitation = await invitations.add(
            email=email,
            role=role.value,
            token_hash=hash_token(token),
            invited_by=actor.id,
            expires_at=datetime.now(UTC) + timedelta(days=settings.invitation_ttl_days),
        )
        link = f"{settings.frontend_origin}/accept-invite?token={token}"
        message = EmailMessage(
            to=email,
            subject=f"{actor.full_name} invited you to {org.name} on TaskFlow",
            body=(
                f"{actor.full_name} invited you to join {org.name} on TaskFlow as {role.value}.\n\n"
                f"Accept the invitation: {link}\n\n"
                f"This link works once and expires in {settings.invitation_ttl_days} days."
            ),
        )
        return IssuedInvitation(invitation=invitation, email=message)

    async def accept(
        self, *, token: str, password: str, full_name: str | None, client: ClientInfo
    ) -> AuthTokens:
        """Redeem an invitation and sign the user in to the organization.

        Everyone proves a password: a new account chooses one, an existing account must supply
        theirs, so possession of the emailed link alone never grants access to an account.
        The invitation is consumed in the same transaction that creates the membership, and
        every failure before that point leaves it usable.
        """
        now = datetime.now(UTC)
        invitation = await self.identity.find_invitation(hash_token(token))
        if invitation is None or invitation.accepted_at is not None or invitation.expires_at <= now:
            raise InvitationNotFoundError()

        user = await self.identity.find_user_by_email(invitation.email)
        if user is not None:
            if not verify_password(password, user.password_hash) or not user.is_active:
                raise InvalidCredentialsError()
            user_id = user.id
        else:
            if not full_name or not full_name.strip():
                raise ValidationFailedError("full_name is required to create a new account")
            if len(password) < MIN_PASSWORD_LENGTH:
                raise ValidationFailedError(
                    f"password must be at least {MIN_PASSWORD_LENGTH} characters"
                )
            user_id = uuid.uuid4()

        org_id = invitation.organization_id
        await set_context(self.session, org_id=org_id, user_id=user_id)
        members = MembershipRepository(self.session, org_id)
        try:
            if user is not None and await members.get_by_user_id(user_id) is not None:
                raise AlreadyMemberError()
            if not await InvitationRepository(self.session, org_id).claim(invitation.id, now):
                raise InvitationNotFoundError()  # lost a race with another accept or expiry
            if user is None:
                await UserRepository(self.session).add(
                    user_id=user_id,
                    email=invitation.email,
                    password_hash=hash_password(password),
                    full_name=(full_name or "").strip(),
                )
            await members.add(user_id=user_id, role=invitation.role)
            tokens, _ = await AuthService(self.session).issue_session(
                user_id, org_id, invitation.role, None, client
            )
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            if "uq_users_email" in str(exc.orig):
                raise EmailAlreadyRegisteredError() from exc
            raise
        return tokens
