"""Domain errors. Services raise these; `app.api.error_handlers` maps them to HTTP responses."""


class AppError(Exception):
    status_code = 500
    code = "INTERNAL_ERROR"
    message = "Internal server error"

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.message)
        self.message = message or self.message


class InvalidCredentialsError(AppError):
    status_code = 401
    code = "INVALID_CREDENTIALS"
    message = "Invalid email or password"


class InvalidTokenError(AppError):
    status_code = 401
    code = "INVALID_TOKEN"
    message = "Invalid or expired access token"


class InvalidRefreshTokenError(AppError):
    status_code = 401
    code = "INVALID_REFRESH_TOKEN"
    message = "Invalid or expired refresh token"


class EmailAlreadyRegisteredError(AppError):
    status_code = 409
    code = "EMAIL_ALREADY_REGISTERED"
    message = "An account with this email already exists"


class NoOrganizationError(AppError):
    status_code = 403
    code = "NO_ORGANIZATION"
    message = "This account does not belong to any organization"


class OrganizationNotFoundError(AppError):
    status_code = 404
    code = "ORGANIZATION_NOT_FOUND"
    message = "Organization not found"


class PermissionDeniedError(AppError):
    status_code = 403
    code = "PERMISSION_DENIED"
    message = "You do not have permission to perform this action"


class ValidationFailedError(AppError):
    status_code = 422
    code = "VALIDATION_ERROR"
    message = "Invalid request"


class InvalidCursorError(AppError):
    status_code = 422
    code = "INVALID_CURSOR"
    message = "Invalid pagination cursor"


class MemberNotFoundError(AppError):
    status_code = 404
    code = "MEMBER_NOT_FOUND"
    message = "Member not found"


class AlreadyMemberError(AppError):
    status_code = 409
    code = "ALREADY_MEMBER"
    message = "This user is already a member of the organization"


class LastAdminError(AppError):
    status_code = 409
    code = "LAST_ADMIN"
    message = "An organization must keep at least one admin"


class InvitationNotFoundError(AppError):
    status_code = 404
    code = "INVITATION_NOT_FOUND"
    message = "Invitation is invalid, expired or already used"
