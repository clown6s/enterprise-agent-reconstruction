"""授权应用程序端口；实现位于此包之外."""
from typing import Protocol

from ..domain.models import Principal, SessionRecord, UserRecord


class UserStore(Protocol):
    def find_by_username(self, tenant_id: str, username: str) -> UserRecord | None: ...
    def find_by_id(self, tenant_id: str, user_id: str) -> UserRecord | None: ...


class SessionStore(Protocol):
    def create(self, tenant_id: str, session_id: str, user_id: str,
               access_token_hash: str, refresh_token_hash: str,
               access_expires_at, refresh_expires_at) -> None: ...
    def find_by_access_hash(self, access_token_hash: str) -> SessionRecord | None: ...
    def find_by_refresh_hash(self, refresh_token_hash: str) -> SessionRecord | None: ...
    def revoke(self, tenant_id: str, session_id: str) -> None: ...


class RolePermissionProvider(Protocol):
    def load(self, tenant_id: str, user_id: str) -> tuple[
        tuple[str, ...], tuple[str, ...], tuple[str, ...]
    ]:
        """Return (roles, department_ids, permissions)."""
        ...