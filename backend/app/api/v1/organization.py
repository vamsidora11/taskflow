import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Path, Query, Response, status

from app.api.deps import (
    AuthSession,
    EmailSenderDep,
    TenantSession,
    get_client_info,
    ip_rate_limit,
    require_permission,
)
from app.api.responses import FORBIDDEN, RATE_LIMITED, UNAUTHORIZED, VALIDATION, error
from app.api.session_cookie import COOKIE_NOTE, set_refresh_cookie, token_response
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from app.core.permissions import Permission
from app.schemas.auth import TokenResponse
from app.schemas.common import Page
from app.schemas.organization import (
    AcceptInvitationRequest,
    InvitationCreate,
    InvitationRead,
    MemberRead,
    MemberRoleUpdate,
    OrganizationRead,
    OrganizationUpdate,
)
from app.services.auth import AuthenticatedUser, ClientInfo
from app.services.email import deliver_email
from app.services.invitation import InvitationService
from app.services.organization import OrganizationService

router = APIRouter(prefix="/api/v1/org", tags=["organization"])

UserIdPath = Annotated[uuid.UUID, Path(description="Id of the member's user account.")]


def _member(row: object) -> MemberRead:
    return MemberRead.model_validate(row, from_attributes=True)


@router.get(
    "",
    response_model=OrganizationRead,
    status_code=status.HTTP_200_OK,
    operation_id="get_organization",
    summary="Get the active organization",
    description=(
        "Returns the organization the access token is scoped to.\n\n"
        "**Roles:** Admin, Manager, Member."
    ),
    responses={**UNAUTHORIZED, **FORBIDDEN, **VALIDATION, **RATE_LIMITED},
)
async def get_organization(
    session: TenantSession,
    user: AuthenticatedUser = Depends(require_permission(Permission.ORG_VIEW)),
) -> OrganizationRead:
    org = await OrganizationService(session, user).get()
    return OrganizationRead.model_validate(org, from_attributes=True)


@router.patch(
    "",
    response_model=OrganizationRead,
    status_code=status.HTTP_200_OK,
    operation_id="update_organization",
    summary="Update organization settings",
    description=(
        "Renames the active organization. Omitted fields are left unchanged.\n\n"
        "**Roles:** Admin.\n\n"
        "**Audit:** will write `org.updated` once the audit log exists (Phase 5)."
    ),
    responses={**UNAUTHORIZED, **FORBIDDEN, **VALIDATION, **RATE_LIMITED},
)
async def update_organization(
    payload: OrganizationUpdate,
    session: TenantSession,
    user: AuthenticatedUser = Depends(require_permission(Permission.ORG_UPDATE)),
) -> OrganizationRead:
    org = await OrganizationService(session, user).update(name=payload.name)
    return OrganizationRead.model_validate(org, from_attributes=True)


@router.get(
    "/members",
    response_model=Page[MemberRead],
    status_code=status.HTTP_200_OK,
    operation_id="list_members",
    summary="List organization members",
    description=(
        "Members of the active organization, oldest first, with cursor pagination.\n\n"
        "**Roles:** Admin, Manager, Member."
    ),
    responses={**UNAUTHORIZED, **FORBIDDEN, **VALIDATION, **RATE_LIMITED},
)
async def list_members(
    session: TenantSession,
    user: AuthenticatedUser = Depends(require_permission(Permission.MEMBER_VIEW)),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT, description="Page size."),
    cursor: str | None = Query(
        None, max_length=200, description="`next_cursor` from the previous page."
    ),
) -> Page[MemberRead]:
    rows, next_cursor = await OrganizationService(session, user).list_members(
        limit=limit, cursor=cursor
    )
    return Page[MemberRead](items=[_member(r) for r in rows], next_cursor=next_cursor)


@router.post(
    "/invitations",
    response_model=InvitationRead,
    status_code=status.HTTP_201_CREATED,
    operation_id="create_invitation",
    summary="Invite someone to the organization",
    description=(
        "Creates a single-use invitation valid for 7 days and emails the link. Inviting an "
        "address again replaces its pending invitation. The link is never returned in the "
        "response. With `EMAIL_BACKEND=console` it is printed to the server output.\n\n"
        "**Roles:** Admin.\n\n"
        "**Audit:** will write `member.invited` once the audit log exists (Phase 5)."
    ),
    responses={
        **UNAUTHORIZED,
        **FORBIDDEN,
        **error(409, "The address already belongs to a member of this organization"),
        **VALIDATION,
        **RATE_LIMITED,
    },
)
async def create_invitation(
    payload: InvitationCreate,
    background_tasks: BackgroundTasks,
    session: TenantSession,
    sender: EmailSenderDep,
    user: AuthenticatedUser = Depends(require_permission(Permission.MEMBER_INVITE)),
) -> InvitationRead:
    issued = await InvitationService(session).invite(
        actor=user, email=payload.email, role=payload.role
    )
    # Background tasks run after the response, i.e. after the invitation has been committed.
    background_tasks.add_task(deliver_email, sender, issued.email)
    return InvitationRead.model_validate(issued.invitation, from_attributes=True)


@router.post(
    "/invitations/{token}/accept",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    operation_id="accept_invitation",
    dependencies=[Depends(ip_rate_limit("accept-invite", "rate_limit_login_per_ip"))],
    summary="Accept an invitation",
    description=(
        "Redeems the emailed token, adds the user to the organization with the invited role, "
        "and signs them in to it.\n\n"
        "**Roles:** public; the token is the credential.\n\n"
        "New addresses create an account (`full_name` and a password of at least 12 characters "
        "are required). Existing accounts must supply their current password. The token works "
        "once; unknown, expired and used tokens all return the same 404.\n\n"
        f"{COOKIE_NOTE}\n\n"
        "**Audit:** will write `member.joined` once the audit log exists (Phase 5)."
    ),
    responses={
        **error(401, "Existing account: wrong password"),
        **error(404, "Invitation is invalid, expired or already used"),
        **error(409, "The user is already a member of the organization"),
        **VALIDATION,
        **RATE_LIMITED,
    },
)
async def accept_invitation(
    payload: AcceptInvitationRequest,
    response: Response,
    session: AuthSession,
    token: Annotated[str, Path(max_length=200, description="Token from the invitation email.")],
    client: ClientInfo = Depends(get_client_info),
) -> TokenResponse:
    tokens = await InvitationService(session).accept(
        token=token, password=payload.password, full_name=payload.full_name, client=client
    )
    set_refresh_cookie(response, tokens)
    return token_response(tokens)


@router.patch(
    "/members/{user_id}",
    response_model=MemberRead,
    status_code=status.HTTP_200_OK,
    operation_id="change_member_role",
    summary="Change a member's role",
    description=(
        "Sets the member's role. The last admin of an organization cannot be demoted.\n\n"
        "**Roles:** Admin.\n\n"
        "**Audit:** will write `member.role_changed` once the audit log exists (Phase 5)."
    ),
    responses={
        **UNAUTHORIZED,
        **FORBIDDEN,
        **error(404, "No such member in the active organization"),
        **error(409, "Would leave the organization without an admin"),
        **VALIDATION,
        **RATE_LIMITED,
    },
)
async def change_member_role(
    user_id: UserIdPath,
    payload: MemberRoleUpdate,
    session: TenantSession,
    user: AuthenticatedUser = Depends(require_permission(Permission.MEMBER_CHANGE_ROLE)),
) -> MemberRead:
    row = await OrganizationService(session, user).change_role(user_id=user_id, role=payload.role)
    return _member(row)


@router.delete(
    "/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="remove_member",
    summary="Remove a member",
    description=(
        "Removes the member and ends their sessions in this organization. The last admin "
        "cannot be removed, including by themselves.\n\n"
        "**Roles:** Admin.\n\n"
        "**Audit:** will write `member.removed` once the audit log exists (Phase 5)."
    ),
    responses={
        **UNAUTHORIZED,
        **FORBIDDEN,
        **error(404, "No such member in the active organization"),
        **error(409, "Would leave the organization without an admin"),
        **VALIDATION,
        **RATE_LIMITED,
    },
)
async def remove_member(
    user_id: UserIdPath,
    session: TenantSession,
    user: AuthenticatedUser = Depends(require_permission(Permission.MEMBER_REMOVE)),
) -> None:
    await OrganizationService(session, user).remove_member(user_id=user_id)
