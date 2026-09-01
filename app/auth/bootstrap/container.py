"""Auth composition root."""
from app.chat.adapters.mysql_pool import MysqlPool

from ..adapters.mysql_role_permission_provider import MysqlRolePermissionProvider
from ..adapters.mysql_session_store import MysqlSessionStore
from ..adapters.mysql_user_store import MysqlUserStore
from ..application.auth_service import AuthService
from .config import read_auth_settings


def build_auth(pool: MysqlPool | None = None) -> AuthService:
    settings = read_auth_settings()
    if pool is None:
        from app.chat.bootstrap.config import read_storage_settings
        storage = read_storage_settings()
        pool = MysqlPool(
            host=storage.mysql_host, port=storage.mysql_port,
            user=storage.mysql_user, password=storage.mysql_password,
            database=storage.mysql_database,
        )
    return AuthService(
        users=MysqlUserStore(pool),
        sessions=MysqlSessionStore(pool),
        permissions=MysqlRolePermissionProvider(pool),
        access_ttl_seconds=settings.access_token_ttl_seconds,
        refresh_ttl_seconds=settings.refresh_token_ttl_seconds,
        token_length=settings.token_length,
    )