import uuid
from datetime import datetime

from sqlalchemy import delete, text

from app.db.models.invitation import Invitation
from app.repositories.base import TenantRepository


class InvitationRepository(TenantRepository[Invitation]):
    model = Invitation

    async def delete_pending_for_email(self, email: str) -> None:
        """Re-inviting an address replaces its unaccepted invitation."""
        await self.session.execute(
            delete(Invitation).where(
                Invitation.organization_id == self.organization_id,
                Invitation.email == email,
                Invitation.accepted_at.is_(None),
            )
        )

    async def claim(self, invitation_id: uuid.UUID, now: datetime) -> bool:
        """Atomically mark an invitation accepted. True only for the single caller that wins.

        The conditions live in the UPDATE itself, so concurrent accepts or an expiry between
        the lookup and this call cannot double-spend the token.
        """
        result = await self.session.execute(
            text(
                "UPDATE invitations SET accepted_at = :now "
                "WHERE id = :id AND organization_id = :org "
                "AND accepted_at IS NULL AND expires_at > :now"
            ),
            {"now": now, "id": invitation_id, "org": self.organization_id},
        )
        return result.rowcount == 1  # type: ignore[attr-defined,no-any-return]
