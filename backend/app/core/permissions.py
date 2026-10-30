"""Roles and the permission matrix (PLAN.md section 5). The single place that maps roles to rights.

Ownership rules ("a member may edit tasks assigned to them") are not expressed here: they depend
on the resource, so they live in the service layer. `TASK_EDIT_OWN` only says the role may use the
ownership path at all.
"""

from enum import StrEnum


class Role(StrEnum):
    ADMIN = "admin"
    MANAGER = "manager"
    MEMBER = "member"


class Permission(StrEnum):
    ORG_VIEW = "org:view"
    ORG_UPDATE = "org:update"
    MEMBER_VIEW = "member:view"
    MEMBER_INVITE = "member:invite"
    MEMBER_CHANGE_ROLE = "member:change_role"
    MEMBER_REMOVE = "member:remove"
    BOARD_VIEW = "board:view"
    BOARD_CREATE = "board:create"
    BOARD_ARCHIVE = "board:archive"
    TASK_VIEW = "task:view"
    TASK_CREATE = "task:create"
    TASK_EDIT_ANY = "task:edit_any"
    TASK_EDIT_OWN = "task:edit_own"
    TASK_DELETE = "task:delete"
    COMMENT_CREATE = "comment:create"
    AUDIT_VIEW = "audit:view"


_EVERYONE = frozenset(Role)
_MANAGERS_UP = frozenset({Role.ADMIN, Role.MANAGER})
_ADMIN_ONLY = frozenset({Role.ADMIN})

# Roles allowed for each permission. Adding a Permission without an entry here fails at import.
_ALLOWED_ROLES: dict[Permission, frozenset[Role]] = {
    Permission.ORG_VIEW: _EVERYONE,
    Permission.ORG_UPDATE: _ADMIN_ONLY,
    Permission.MEMBER_VIEW: _EVERYONE,
    Permission.MEMBER_INVITE: _ADMIN_ONLY,
    Permission.MEMBER_CHANGE_ROLE: _ADMIN_ONLY,
    Permission.MEMBER_REMOVE: _ADMIN_ONLY,
    Permission.BOARD_VIEW: _EVERYONE,
    Permission.BOARD_CREATE: _MANAGERS_UP,
    Permission.BOARD_ARCHIVE: _MANAGERS_UP,
    Permission.TASK_VIEW: _EVERYONE,
    Permission.TASK_CREATE: _EVERYONE,
    Permission.TASK_EDIT_ANY: _MANAGERS_UP,
    Permission.TASK_EDIT_OWN: _EVERYONE,
    Permission.TASK_DELETE: _MANAGERS_UP,
    Permission.COMMENT_CREATE: _EVERYONE,
    Permission.AUDIT_VIEW: _MANAGERS_UP,
}

missing = set(Permission) - set(_ALLOWED_ROLES)
if missing:  # pragma: no cover - guards future edits
    raise RuntimeError(f"permissions without a role mapping: {sorted(missing)}")

ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    role: frozenset(p for p, roles in _ALLOWED_ROLES.items() if role in roles) for role in Role
}


def has_permission(role: Role | str, permission: Permission) -> bool:
    try:
        return permission in ROLE_PERMISSIONS[Role(role)]
    except ValueError:  # unknown role string: deny
        return False
