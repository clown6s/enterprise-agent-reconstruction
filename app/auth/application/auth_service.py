"""身份验证使用场景，独立于HTTP和数据库细节."""
from datetime import datetime, timedelta, timezone
import uuid

from ..domain.exceptions import InvalidCredentialsError, InvalidTokenError, TokenExpiredError
from ..domain.models import LoginResult, Principal
from .password import verify_password
from .ports import RolePermissionProvider, SessionStore, UserStore
from .token_service import generate_token, sha256


def _as_utc(value: datetime) -> datetime:
    """统一处理 MySQL DATETIME 返回的无时区时间。"""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class AuthService:
    def __init__(self, users: UserStore, sessions: SessionStore,
                 permissions: RolePermissionProvider, *,
                 access_ttl_seconds: int = 900,
                 refresh_ttl_seconds: int = 604800,
                 token_length: int = 32,
                 clock=None):
        self.users = users
        self.sessions = sessions
        self.permissions = permissions
        self.access_ttl_seconds = access_ttl_seconds
        self.refresh_ttl_seconds = refresh_ttl_seconds
        self.token_length = token_length
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def login(self, tenant_id: str, username: str, password: str) -> LoginResult:
        user = self.users.find_by_username(tenant_id, username)
        if user is None or user.status != "active" or not verify_password(password, user.password_hash):
            raise InvalidCredentialsError("用户名或密码错误")
        roles, departments, permissions = self.permissions.load(tenant_id, user.user_id)
        now = self.clock()
        access_expires = now + timedelta(seconds=self.access_ttl_seconds)
        refresh_expires = now + timedelta(seconds=self.refresh_ttl_seconds)
        access = generate_token(self.token_length)
        refresh = generate_token(self.token_length)
        session_id = str(uuid.uuid4())
        self.sessions.create(
            tenant_id, session_id, user.user_id, sha256(access), sha256(refresh),
            access_expires, refresh_expires,
        )
        principal = Principal(
            tenant_id=tenant_id, user_id=user.user_id, username=user.username,
            roles=roles, department_ids=departments, permissions=permissions,
            session_id=session_id, expires_at=access_expires,
        )
        return LoginResult(access, refresh, self.access_ttl_seconds, principal)

    def verify_access(self, token: str) -> Principal:
        if not token:
            raise InvalidTokenError("缺少访问令牌")
        session = self.sessions.find_by_access_hash(sha256(token))
        if session is None:
            raise InvalidTokenError("访问令牌无效或已吊销")
        now = self.clock()
        if (session.access_expires_at is None
                or _as_utc(session.access_expires_at) <= _as_utc(now)):
            raise TokenExpiredError("访问令牌已过期")
        user = self.users.find_by_id(session.tenant_id, session.user_id)
        if user is None or user.status != "active":
            raise InvalidTokenError("用户无效或已禁用")
        roles, departments, permissions = self.permissions.load(
            session.tenant_id, session.user_id)
        return Principal(
            tenant_id=session.tenant_id, user_id=session.user_id,
            username=user.username, roles=roles, department_ids=departments,
            permissions=permissions, session_id=session.session_id,
            expires_at=session.access_expires_at,
        )

    def refresh(self, refresh_token: str) -> LoginResult:
        if not refresh_token:
            raise InvalidTokenError("缺少刷新令牌")
        session = self.sessions.find_by_refresh_hash(sha256(refresh_token))
        if session is None:
            raise InvalidTokenError("刷新令牌无效或已吊销")
        now = self.clock()
        if _as_utc(session.expires_at) <= _as_utc(now):
            raise TokenExpiredError("刷新令牌已过期")
        user = self.users.find_by_id(session.tenant_id, session.user_id)
        if user is None or user.status != "active":
            raise InvalidTokenError("用户无效或已禁用")
        roles, departments, permissions = self.permissions.load(
            session.tenant_id, session.user_id)
        access_expires = now + timedelta(seconds=self.access_ttl_seconds)
        refresh_expires = now + timedelta(seconds=self.refresh_ttl_seconds)
        access = generate_token(self.token_length)
        replacement = generate_token(self.token_length)
        self.sessions.revoke(session.tenant_id, session.session_id)
        self.sessions.create(
            session.tenant_id, str(uuid.uuid4()), session.user_id,
            sha256(access), sha256(replacement), access_expires, refresh_expires,
        )
        principal = Principal(
            tenant_id=session.tenant_id, user_id=session.user_id,
            username=user.username, roles=roles, department_ids=departments,
            permissions=permissions, expires_at=access_expires,
        )
        return LoginResult(access, replacement, self.access_ttl_seconds, principal)

    def logout(self, principal: Principal) -> None:
        if principal.session_id:
            self.sessions.revoke(principal.tenant_id, principal.session_id)

    def require(self, principal: Principal, permission: str) -> None:
        if not principal.can(permission):
            from ..domain.exceptions import InsufficientPermissionError
            raise InsufficientPermissionError("无权执行该操作")
