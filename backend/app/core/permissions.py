"""Roles and permissions. The permission enum and role map arrive in Phase 3."""

from enum import StrEnum


class Role(StrEnum):
    ADMIN = "admin"
    MANAGER = "manager"
    MEMBER = "member"
