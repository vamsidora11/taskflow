import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.core.permissions import Role
from app.core.security import MIN_PASSWORD_LENGTH


class SignupRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "organization_name": "Acme Inc",
                    "email": "ada@acme.example",
                    "password": "correct horse battery staple",
                    "full_name": "Ada Lovelace",
                }
            ]
        }
    )

    organization_name: str = Field(
        min_length=1, max_length=200, description="Name of the new organization."
    )
    email: EmailStr = Field(description="Login email. Stored lowercased and must be unique.")
    password: str = Field(
        min_length=MIN_PASSWORD_LENGTH,
        max_length=128,
        description=f"At least {MIN_PASSWORD_LENGTH} characters.",
    )
    full_name: str = Field(min_length=1, max_length=200, description="Display name of the user.")


class LoginRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"email": "ada@acme.example", "password": "correct horse battery staple"}]
        }
    )

    email: EmailStr = Field(description="Login email (case-insensitive).")
    password: str = Field(min_length=1, max_length=128, description="Account password.")


class SwitchOrganizationRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"organization_id": "0b7c1f2e-9a3d-4c5b-8e7f-1a2b3c4d5e6f"}]
        }
    )

    organization_id: uuid.UUID = Field(
        description="Organization to make active. The caller must be a member."
    )


class TokenResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                    "token_type": "bearer",
                    "expires_in": 900,
                    "organization_id": "0b7c1f2e-9a3d-4c5b-8e7f-1a2b3c4d5e6f",
                    "role": "admin",
                }
            ]
        }
    )

    access_token: str = Field(description="Short-lived JWT. Send as `Authorization: Bearer`.")
    token_type: Literal["bearer"] = Field(description="Always `bearer`.")
    expires_in: int = Field(description="Access token lifetime in seconds.")
    organization_id: uuid.UUID = Field(description="Organization the token is scoped to.")
    role: Role = Field(description="Caller's role in that organization.")


class UserRead(BaseModel):
    id: uuid.UUID = Field(description="User id.")
    email: str = Field(description="Login email.")
    full_name: str = Field(description="Display name.")


class OrganizationSummary(BaseModel):
    id: uuid.UUID = Field(description="Organization id.")
    name: str = Field(description="Organization name.")
    slug: str = Field(description="URL-safe unique name.")
    role: Role = Field(description="Caller's role in this organization.")


class MeResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "user": {
                        "id": "5d0c3b1e-7a52-4f5e-9d54-0c8f0a5e1a11",
                        "email": "ada@acme.example",
                        "full_name": "Ada Lovelace",
                    },
                    "active_organization": {
                        "id": "0b7c1f2e-9a3d-4c5b-8e7f-1a2b3c4d5e6f",
                        "name": "Acme Inc",
                        "slug": "acme-inc-a1b2c3",
                        "role": "admin",
                    },
                    "organizations": [
                        {
                            "id": "0b7c1f2e-9a3d-4c5b-8e7f-1a2b3c4d5e6f",
                            "name": "Acme Inc",
                            "slug": "acme-inc-a1b2c3",
                            "role": "admin",
                        }
                    ],
                }
            ]
        }
    )

    user: UserRead = Field(description="The authenticated user.")
    active_organization: OrganizationSummary = Field(
        description="Organization the access token is scoped to."
    )
    organizations: list[OrganizationSummary] = Field(
        description="Every organization the user belongs to, for the org switcher."
    )
