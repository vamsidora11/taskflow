"""Create two demo organizations with realistic sample data.

    cd backend && python -m scripts.seed

Runs through the same services the API uses, as the unprivileged `app_user` role, so passwords
are Argon2-hashed, row-level security applies and the audit log is populated exactly as it would
be for real traffic. Safe to run twice: it does nothing if the demo accounts already exist.

DEMO ONLY: every account shares one published password. Never run this against production.
"""

import asyncio
import re
import sys
from datetime import date, timedelta

from app.core.enums import Priority
from app.core.permissions import Role
from app.core.security import decode_access_token
from app.db.session import SessionFactory, get_session_factory, tenant_session
from app.repositories.identity import IdentityRepository
from app.services.auth import AuthenticatedUser, AuthService, AuthTokens, ClientInfo
from app.services.board import BoardService
from app.services.comment import CommentService
from app.services.invitation import InvitationService
from app.services.task import TaskService

DEMO_PASSWORD = "demo-password-123"  # noqa: S105 - published demo credential, not a secret

ACME_ADMIN = "ada@acme.example"
ACME_MANAGER = "grace@acme.example"
ACME_MEMBER = "alan@acme.example"
GLOBEX_ADMIN = "hank@globex.example"
GLOBEX_MEMBER = "alan@acme.example"  # belongs to both organizations: shows the org switcher

CREDENTIALS = [
    ("Acme Corp", "admin", ACME_ADMIN),
    ("Acme Corp", "manager", ACME_MANAGER),
    ("Acme Corp and Globex", "member", ACME_MEMBER),
    ("Globex Inc", "admin", GLOBEX_ADMIN),
]


async def _actor(tokens: AuthTokens, email: str, name: str) -> AuthenticatedUser:
    claims = decode_access_token(tokens.access_token)
    return AuthenticatedUser(
        id=claims.user_id,
        email=email,
        full_name=name,
        organization_id=claims.org_id,
        role=claims.role,
    )


async def _join(
    factory: SessionFactory,
    admin: AuthenticatedUser,
    email: str,
    name: str,
    role: Role,
    password: str,
) -> AuthenticatedUser:
    """Invite `email` to the admin's organization and accept, exactly as the two API calls would."""
    async with tenant_session(factory, admin.organization_id, admin.id) as session:
        issued = await InvitationService(session).invite(actor=admin, email=email, role=role)
    match = re.search(r"token=([A-Za-z0-9_-]+)", issued.email.body)
    assert match, "invitation email had no token"
    async with factory() as session:
        tokens = await InvitationService(session).accept(
            token=match.group(1), password=password, full_name=name, client=ClientInfo()
        )
    return await _actor(tokens, email, name)


async def seed(factory: SessionFactory) -> bool:
    """Returns False (and changes nothing) if the demo data already exists."""
    async with factory() as session:
        if await IdentityRepository(session).find_user_by_email(ACME_ADMIN) is not None:
            return False

    # --- Acme Corp ---------------------------------------------------------------------
    async with factory() as session:
        tokens = await AuthService(session).signup(
            organization_name="Acme Corp",
            email=ACME_ADMIN,
            password=DEMO_PASSWORD,
            full_name="Ada Lovelace",
            client=ClientInfo(),
        )
    ada = await _actor(tokens, ACME_ADMIN, "Ada Lovelace")
    grace = await _join(factory, ada, ACME_MANAGER, "Grace Hopper", Role.MANAGER, DEMO_PASSWORD)
    alan = await _join(factory, ada, ACME_MEMBER, "Alan Turing", Role.MEMBER, DEMO_PASSWORD)

    today = date.today()
    async with tenant_session(factory, ada.organization_id, ada.id) as session:
        roadmap, columns = await BoardService(session, grace).create_board(
            name="Product Roadmap",
            description="What we are building this quarter.",
            columns=["Backlog", "In Progress", "Review", "Done"],
        )
        backlog, doing, review, done = (c.id for c in columns)
        tasks = TaskService(session, grace)
        spec = [
            ("Define Q4 OKRs", done, Priority.HIGH, ada, -10),
            ("Design onboarding flow", review, Priority.HIGH, alan, 2),
            ("Implement SSO login", doing, Priority.URGENT, grace, 5),
            ("Write API documentation", doing, Priority.MEDIUM, alan, 7),
            ("Migrate billing provider", backlog, Priority.MEDIUM, None, 21),
            ("Accessibility audit", backlog, Priority.LOW, None, 30),
            ("Reduce page load time", backlog, Priority.HIGH, grace, 14),
            ("Customer interview round 2", review, Priority.MEDIUM, ada, 3),
        ]
        created = {}
        for title, column, priority, who, days in spec:
            created[title] = await tasks.create_task(
                roadmap.id,
                title=title,
                description=f"Seeded task: {title}.",
                priority=priority,
                assignee_id=who.id if who else None,
                due_date=today + timedelta(days=days),
                column_id=column,
            )
        await tasks.move_task(created["Define Q4 OKRs"].id, column_id=done, position=0)
        for who, task_title, body in (
            (alan, "Design onboarding flow", "First draft is in Figma, ready for review."),
            (grace, "Design onboarding flow", "Looks good. Can we shorten step 3?"),
            (ada, "Implement SSO login", "Prioritising this: two customers are blocked on it."),
        ):
            await CommentService(session, who).add_comment(created[task_title].id, body=body)

        await BoardService(session, ada).create_board(
            name="Marketing Launch", description="Launch plan for v2.", columns=None
        )

    # --- Globex Inc ------------------------------------------------------------------------
    async with factory() as session:
        tokens = await AuthService(session).signup(
            organization_name="Globex Inc",
            email=GLOBEX_ADMIN,
            password=DEMO_PASSWORD,
            full_name="Hank Scorpio",
            client=ClientInfo(),
        )
    hank = await _actor(tokens, GLOBEX_ADMIN, "Hank Scorpio")
    alan_at_globex = await _join(
        factory, hank, GLOBEX_MEMBER, "Alan Turing", Role.MEMBER, DEMO_PASSWORD
    )
    async with tenant_session(factory, hank.organization_id, hank.id) as session:
        ops, columns = await BoardService(session, hank).create_board(
            name="Operations", description="Keeping the lights on.", columns=None
        )
        todo = columns[0].id
        tasks = TaskService(session, hank)
        for title, priority, who in (
            ("Renew data-centre lease", Priority.HIGH, hank),
            ("Order replacement servers", Priority.MEDIUM, alan_at_globex),
            ("Review security policy", Priority.LOW, None),
        ):
            await tasks.create_task(
                ops.id,
                title=title,
                description=None,
                priority=priority,
                assignee_id=who.id if who else None,
                due_date=today + timedelta(days=10),
                column_id=todo,
            )
    return True


async def main() -> int:
    if not await seed(get_session_factory()):
        print("Demo data already exists; nothing to do.")
        return 0
    print(f"Seeded two organizations. Every account uses the password {DEMO_PASSWORD!r}:\n")
    for org, role, email in CREDENTIALS:
        print(f"  {org:22} {role:8} {email}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
