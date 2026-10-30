"""The permission matrix, written out independently of the implementation (PLAN.md section 5).

If a permission is added or a cell changes in `app/core/permissions.py`, this file must change
with it. That is the point: the matrix is a security contract, not an implementation detail.
"""

import pytest

from app.core.permissions import ROLE_PERMISSIONS, Permission, Role, has_permission

A, M, U = Role.ADMIN, Role.MANAGER, Role.MEMBER  # admin, manager, member

# permission -> roles that hold it. Rows follow the table in section 5.
EXPECTED: dict[Permission, set[Role]] = {
    # Update organization settings
    Permission.ORG_UPDATE: {A},
    # Invite / remove users, change roles
    Permission.MEMBER_INVITE: {A},
    Permission.MEMBER_REMOVE: {A},
    Permission.MEMBER_CHANGE_ROLE: {A},
    # Create / archive boards
    Permission.BOARD_CREATE: {A, M},
    Permission.BOARD_ARCHIVE: {A, M},
    # Create tasks
    Permission.TASK_CREATE: {A, M, U},
    # Edit any task
    Permission.TASK_EDIT_ANY: {A, M},
    # Edit tasks assigned to self
    Permission.TASK_EDIT_OWN: {A, M, U},
    # Delete tasks
    Permission.TASK_DELETE: {A, M},
    # Comment on tasks
    Permission.COMMENT_CREATE: {A, M, U},
    # View activity log
    Permission.AUDIT_VIEW: {A, M},
    # View boards and tasks (plus the organization and its member list)
    Permission.BOARD_VIEW: {A, M, U},
    Permission.TASK_VIEW: {A, M, U},
    Permission.ORG_VIEW: {A, M, U},
    Permission.MEMBER_VIEW: {A, M, U},
}

ALL_CELLS = [(p, r) for p in Permission for r in Role]


def test_every_permission_has_an_expected_row() -> None:
    assert set(EXPECTED) == set(Permission)


@pytest.mark.parametrize(
    ("permission", "role"), ALL_CELLS, ids=[f"{p.value}-{r.value}" for p, r in ALL_CELLS]
)
def test_matrix_cell(permission: Permission, role: Role) -> None:
    assert has_permission(role, permission) is (role in EXPECTED[permission])


def test_role_permission_sets_nest() -> None:
    assert ROLE_PERMISSIONS[Role.MEMBER] < ROLE_PERMISSIONS[Role.MANAGER]
    assert ROLE_PERMISSIONS[Role.MANAGER] < ROLE_PERMISSIONS[Role.ADMIN]
    assert ROLE_PERMISSIONS[Role.ADMIN] == frozenset(Permission)


def test_accepts_role_strings_as_stored_in_the_database() -> None:
    assert has_permission("admin", Permission.ORG_UPDATE)
    assert not has_permission("member", Permission.ORG_UPDATE)


@pytest.mark.parametrize("role", ["", "owner", "ADMIN", "superuser"])
def test_unknown_roles_hold_nothing(role: str) -> None:
    assert not any(has_permission(role, p) for p in Permission)
