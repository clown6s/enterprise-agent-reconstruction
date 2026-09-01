import hashlib
from datetime import datetime, timedelta, timezone

import pytest

from app.auth.application.auth_service import AuthService
from app.auth.application.password import hash_password, verify_password
from app.auth.domain.exceptions import InvalidCredentialsError, InvalidTokenError, TokenExpiredError
from app.auth.domain.models import SessionRecord, UserRecord


class Users:
    def __init__(self):
        self.user = UserRecord("tenant-test", "user-test-001", "test_user", hash_password("Test@123456"))

    def find_by_username(self, tenant_id, username):
        return self.user if (tenant_id, username) == (self.user.tenant_id, self.user.username) else None

    def find_by_id(self, tenant_id, user_id):
        return self.user if (tenant_id, user_id) == (self.user.tenant_id, self.user.user_id) else None


class Sessions:
    def __init__(self):
        self.rows = {}
        self.revoked = []

    def create(self, tenant_id, session_id, user_id, access_hash, refresh_hash, access_exp, refresh_exp):
        self.rows[access_hash] = SessionRecord(tenant_id, session_id, user_id, refresh_exp, access_exp)
        self.rows[refresh_hash] = self.rows[access_hash]

    def find_by_access_hash(self, value):
        return self.rows.get(value) if value not in self.revoked else None

    def find_by_refresh_hash(self, value):
        return self.rows.get(value) if value not in self.revoked else None

    def revoke(self, tenant_id, session_id):
        self.revoked.extend(k for k, row in self.rows.items()
                            if row.tenant_id == tenant_id and row.session_id == session_id)


class Permissions:
    def load(self, tenant_id, user_id):
        return ("employee",), ("dept-tech",), ("chat:ask", "sop:read", "sql:read")


def _service(now=None):
    return AuthService(Users(), Sessions(), Permissions(), clock=now or (lambda: datetime.now(timezone.utc)))


def test_password_roundtrip():
    encoded = hash_password("secret")
    assert encoded != "secret"
    assert verify_password("secret", encoded)
    assert not verify_password("wrong", encoded)


def test_login_and_verify_access():
    service = _service()
    result = service.login("tenant-test", "test_user", "Test@123456")
    principal = service.verify_access(result.access_token)
    assert principal.user_id == "user-test-001"
    assert principal.can("sql:read")
    assert result.refresh_token != result.access_token


def test_wrong_credentials_rejected():
    with pytest.raises(InvalidCredentialsError):
        _service().login("tenant-test", "test_user", "wrong")


def test_logout_revokes_access():
    service = _service()
    result = service.login("tenant-test", "test_user", "Test@123456")
    service.logout(result.principal)
    with pytest.raises(InvalidTokenError):
        service.verify_access(result.access_token)


def test_expired_access_rejected():
    now = datetime.now(timezone.utc)
    service = AuthService(Users(), Sessions(), Permissions(),
                          access_ttl_seconds=-1, clock=lambda: now)
    result = service.login("tenant-test", "test_user", "Test@123456")
    with pytest.raises(TokenExpiredError):
        service.verify_access(result.access_token)
