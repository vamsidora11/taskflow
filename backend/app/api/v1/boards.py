import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, status

from app.api.deps import TenantSession, require_permission
from app.api.responses import FORBIDDEN, RATE_LIMITED, UNAUTHORIZED, VALIDATION, error
from app.core.exceptions import PermissionDeniedError
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from app.core.permissions import Permission, has_permission
from app.schemas.board import (
    BoardCreate,
    BoardDetail,
    BoardRead,
    BoardUpdate,
    ColumnCreate,
    ColumnRead,
    ColumnUpdate,
)
from app.schemas.common import Page
from app.services.auth import AuthenticatedUser
from app.services.board import BoardService

router = APIRouter(prefix="/api/v1", tags=["boards"])

BoardIdPath = Annotated[uuid.UUID, Path(description="Board id.")]
ColumnIdPath = Annotated[uuid.UUID, Path(description="Column id.")]

_COMMON = {**UNAUTHORIZED, **FORBIDDEN, **VALIDATION, **RATE_LIMITED}
_NO_BOARD = error(404, "Board not found in the active organization")
_ARCHIVED = error(409, "The board is archived")


@router.get(
    "/boards",
    response_model=Page[BoardRead],
    status_code=status.HTTP_200_OK,
    operation_id="list_boards",
    summary="List boards",
    description=(
        "Boards of the active organization, oldest first, with cursor pagination. Archived "
        "boards are hidden unless `include_archived` is true.\n\n**Roles:** Admin, Manager, Member."
    ),
    responses=_COMMON,
)
async def list_boards(
    session: TenantSession,
    user: AuthenticatedUser = Depends(require_permission(Permission.BOARD_VIEW)),
    include_archived: bool = Query(False, description="Also return archived boards."),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT, description="Page size."),
    cursor: str | None = Query(None, max_length=200, description="`next_cursor` of the last page."),
) -> Page[BoardRead]:
    boards, next_cursor = await BoardService(session, user).list_boards(
        include_archived=include_archived, limit=limit, cursor=cursor
    )
    return Page[BoardRead](items=[BoardRead.from_board(b) for b in boards], next_cursor=next_cursor)


@router.post(
    "/boards",
    response_model=BoardDetail,
    status_code=status.HTTP_201_CREATED,
    operation_id="create_board",
    summary="Create a board",
    description=(
        "Creates a board with its columns (To Do, In Progress and Done unless `columns` is "
        "given).\n\n**Roles:** Admin, Manager.\n\n"
        "**Audit:** will write `board.created` once the audit log exists (Phase 5)."
    ),
    responses=_COMMON,
)
async def create_board(
    payload: BoardCreate,
    session: TenantSession,
    user: AuthenticatedUser = Depends(require_permission(Permission.BOARD_CREATE)),
) -> BoardDetail:
    board, columns = await BoardService(session, user).create_board(
        name=payload.name, description=payload.description, columns=payload.columns
    )
    return BoardDetail.build(board, columns)


@router.get(
    "/boards/{board_id}",
    response_model=BoardDetail,
    status_code=status.HTTP_200_OK,
    operation_id="get_board",
    summary="Get a board with its columns",
    description="**Roles:** Admin, Manager, Member.",
    responses={**_COMMON, **_NO_BOARD},
)
async def get_board(
    board_id: BoardIdPath,
    session: TenantSession,
    user: AuthenticatedUser = Depends(require_permission(Permission.BOARD_VIEW)),
) -> BoardDetail:
    board, columns = await BoardService(session, user).get_board(board_id)
    return BoardDetail.build(board, columns)


@router.patch(
    "/boards/{board_id}",
    response_model=BoardRead,
    status_code=status.HTTP_200_OK,
    operation_id="update_board",
    summary="Update a board",
    description=(
        "Renames the board, changes its description, or archives and restores it. Omitted "
        "fields are unchanged.\n\n**Roles:** Admin, Manager.\n\n"
        "**Audit:** will write `board.updated` or `board.archived` (Phase 5)."
    ),
    responses={**_COMMON, **_NO_BOARD},
)
async def update_board(
    board_id: BoardIdPath,
    payload: BoardUpdate,
    session: TenantSession,
    user: AuthenticatedUser = Depends(require_permission(Permission.BOARD_CREATE)),
) -> BoardRead:
    if payload.is_archived is not None and not has_permission(user.role, Permission.BOARD_ARCHIVE):
        raise PermissionDeniedError()
    board = await BoardService(session, user).update_board(
        board_id,
        name=payload.name,
        description=payload.description,
        description_given="description" in payload.model_fields_set,
        is_archived=payload.is_archived,
    )
    return BoardRead.from_board(board)


@router.delete(
    "/boards/{board_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="archive_board",
    summary="Archive a board",
    description=(
        "Archives the board: it becomes read-only and is hidden from the default list. Nothing "
        "is deleted, and archiving an archived board succeeds. Restore with `PATCH` "
        "`is_archived: false`.\n\n**Roles:** Admin, Manager.\n\n"
        "**Audit:** will write `board.archived` (Phase 5)."
    ),
    responses={**_COMMON, **_NO_BOARD},
)
async def archive_board(
    board_id: BoardIdPath,
    session: TenantSession,
    user: AuthenticatedUser = Depends(require_permission(Permission.BOARD_ARCHIVE)),
) -> None:
    await BoardService(session, user).archive_board(board_id)


@router.post(
    "/boards/{board_id}/columns",
    response_model=ColumnRead,
    status_code=status.HTTP_201_CREATED,
    operation_id="create_column",
    summary="Add a column to a board",
    description=(
        "Adds a column at `position`, or at the far right. Later columns shift right.\n\n"
        "**Roles:** Admin, Manager."
    ),
    responses={**_COMMON, **_NO_BOARD, **_ARCHIVED},
)
async def create_column(
    board_id: BoardIdPath,
    payload: ColumnCreate,
    session: TenantSession,
    user: AuthenticatedUser = Depends(require_permission(Permission.BOARD_CREATE)),
) -> ColumnRead:
    column = await BoardService(session, user).add_column(
        board_id, name=payload.name, position=payload.position
    )
    return ColumnRead.from_column(column)


@router.patch(
    "/columns/{column_id}",
    response_model=ColumnRead,
    status_code=status.HTTP_200_OK,
    operation_id="update_column",
    summary="Rename or reorder a column",
    description=(
        "Renames the column and/or moves it to `position`; the other columns shift to make "
        "room.\n\n**Roles:** Admin, Manager."
    ),
    responses={**_COMMON, **error(404, "Column not found"), **_ARCHIVED},
)
async def update_column(
    column_id: ColumnIdPath,
    payload: ColumnUpdate,
    session: TenantSession,
    user: AuthenticatedUser = Depends(require_permission(Permission.BOARD_CREATE)),
) -> ColumnRead:
    column = await BoardService(session, user).update_column(
        column_id, name=payload.name, position=payload.position
    )
    return ColumnRead.from_column(column)


@router.delete(
    "/columns/{column_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="delete_column",
    summary="Delete an empty column",
    description=(
        "Deletes the column and closes the gap. A column that still holds tasks is refused "
        "with 409; move or delete its tasks first.\n\n**Roles:** Admin, Manager."
    ),
    responses={
        **_COMMON,
        **error(404, "Column not found"),
        **error(409, "The column still has tasks, or the board is archived"),
    },
)
async def delete_column(
    column_id: ColumnIdPath,
    session: TenantSession,
    user: AuthenticatedUser = Depends(require_permission(Permission.BOARD_CREATE)),
) -> None:
    await BoardService(session, user).delete_column(column_id)
