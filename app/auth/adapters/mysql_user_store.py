"""用于身份验证的 MySQL 用户存储（读取 auth_users）."""
from ..application.ports import UserStore
from ..domain.models import UserRecord
from app.chat.adapters.mysql_pool import MysqlPool, mysql_errors


class MysqlUserStore(UserStore):
    """只读查询 auth_users；从不存储凭据."""

    def __init__(self, pool: MysqlPool):
        self._pool = pool

    @mysql_errors
    def find_by_username(self, tenant_id: str, username: str) -> UserRecord | None:
        def op(conn):
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT tenant_id, user_id, username, password_hash, status "
                    "FROM auth_users WHERE tenant_id=%s AND username=%s LIMIT 1",
                    (tenant_id, username),
                )
                row = cur.fetchone()
            if row is None:
                return None
            return UserRecord(
                tenant_id=row["tenant_id"], user_id=row["user_id"],
                username=row["username"], password_hash=row["password_hash"],
                status=row["status"],
            )
        return self._pool.run(op)

    @mysql_errors
    def find_by_id(self, tenant_id: str, user_id: str) -> UserRecord | None:
        def op(conn):
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT tenant_id, user_id, username, password_hash, status "
                    "FROM auth_users WHERE tenant_id=%s AND user_id=%s LIMIT 1",
                    (tenant_id, user_id),
                )
                row = cur.fetchone()
            if row is None:
                return None
            return UserRecord(
                tenant_id=row["tenant_id"], user_id=row["user_id"],
                username=row["username"], password_hash=row["password_hash"],
                status=row["status"],
            )
        return self._pool.run(op)