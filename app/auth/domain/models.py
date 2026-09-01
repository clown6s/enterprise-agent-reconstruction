"""Authentication domain models without framework dependencies."""
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Principal:
    tenant_id: str
    user_id: str
    username: str
    roles: tuple[str, ...] = ()
    department_ids: tuple[str, ...] = ()
    permissions: tuple[str, ...] = ()
    session_id: str | None = None
    expires_at: datetime | None = None

    def can(self, permission: str) -> bool:
        return permission in self.permissions


@dataclass(frozen=True)
class UserRecord:
    tenant_id: str
    user_id: str
    username: str
    password_hash: str
    status: str = "active"


@dataclass(frozen=True)
class SessionRecord:
    tenant_id: str
    session_id: str
    user_id: str
    expires_at: datetime          # refresh token 过期时间
    access_expires_at: datetime | None = None
    status: str = "active"


@dataclass(frozen=True)
class LoginResult:
    access_token: str
    refresh_token: str
    expires_in: int
    principal: Principal
