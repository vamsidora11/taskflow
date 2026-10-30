import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.core.permissions import Role


class OrganizationRead(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "id": "0b7c1f2e-9a3d-4c5b-8e7f-1a2b3c4d5e6f",
                    "name": "Acme Inc",
                    "slug": "acme-inc-a1b2c3",
                    "created_at": "2026-10-30T09:00:00Z",
                }
            ]
        }
    )

    id: uuid.UUID = Field(description="Organization id.")
    name: str = Field(description="Organization name.")
    slug: str = Field(description="URL-safe unique name. Fixed at creation.")
    created_at: datetime = Field(description="When the organization was created (UTC).")


class OrganizationUpdate(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{"name": "Acme Corporation"}]})

    name: str | None = Field(
        default=None, min_length=1, max_length=200, description="New organization name."
    )


class MemberRead(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "user_id": "5d0c3b1e-7a52-4f5e-9d54-0c8f0a5e1a11",
                    "email": "ada@acme.example",
                    "full_name": "Ada Lovelace",
                    "role": "admin",
                    "joined_at": "2026-10-30T09:00:00Z",
                }
            ]
        }
    )

    user_id: uuid.UUID = Field(description="User id.")
    email: str = Field(description="Login email.")
    full_name: str = Field(description="Display name.")
    role: Role = Field(description="Role in this organization.")
    joined_at: datetime = Field(description="When the user joined the organization (UTC).")


class MemberRoleUpdate(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{"role": "manager"}]})

    role: Role = Field(description="New role. The last admin cannot be demoted.")


class InvitationCreate(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"examples": [{"email": "grace@acme.example", "role": "member"}]}
    )

    email: EmailStr = Field(description="Address to invite. Stored lowercased.")
    role: Role = Field(default=Role.MEMBER, description="Role the invitee receives on joining.")


class InvitationRead(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "id": "7c1d5e0a-3b2f-4a6d-8c9e-0f1a2b3c4d5e",
                    "email": "grace@acme.example",
                    "role": "member",
                    "expires_at": "2026-11-06T09:00:00Z",
                    "created_at": "2026-10-30T09:00:00Z",
                }
            ]
        }
    )

    id: uuid.UUID = Field(description="Invitation id.")
    email: str = Field(description="Invited address.")
    role: Role = Field(description="Role the invitee will receive.")
    expires_at: datetime = Field(description="After this the link stops working (UTC).")
    created_at: datetime = Field(description="When the invitation was created (UTC).")


class AcceptInvitationRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"password": "correct horse battery staple", "full_name": "Grace Hopper"}]
        }
    )

    password: str = Field(
        min_length=1,
        max_length=128,
        description=(
            "New accounts: the password to set (at least 12 characters). Existing accounts: "
            "the account's current password."
        ),
    )
    full_name: str | None = Field(
        default=None,
        max_length=200,
        description="Display name. Required only when the invited address has no account yet.",
    )
