"""Auth-specific errors; stack-independent, translated at the API layer."""
from app.ingestion.domain.exceptions import AppError, InfrastructureError, ValidationError


class AuthError(ValidationError):
    """Base authentication failure; mapped to 401/400 at the API layer."""


class InvalidCredentialsError(AuthError):
    """Wrong username/password or disabled/locked account."""


class InvalidTokenError(AuthError):
    """Token missing, malformed, expired, or revoked."""


class TokenExpiredError(InvalidTokenError):
    """Token present but expired."""


class TokenRevokedError(InvalidTokenError):
    """Token was revoked explicitly."""


class InsufficientPermissionError(ValidationError):
    """Authenticated principal lacks a required permission."""


class AuthInfrastructureError(InfrastructureError):
    """Auth backing store (MySQL) failed."""