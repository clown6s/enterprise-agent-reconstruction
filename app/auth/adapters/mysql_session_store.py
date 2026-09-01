"""MySQL session store for revocable opaque auth tokens."""
from ..application.ports import SessionStore
from ..domain.models import SessionRecord
from app.chat.adapters.mysql_pool import MysqlPool, mysql_errors


class MysqlSessionStore(SessionStore):
    def __init__(self, pool: MysqlPool):
        self._pool = pool

    @mysql_errors
    def create(self, tenant_id: str, session_id: str, user_id: str,
               access_token_hash: str, refresh_token_hash: str,
               access_expires_at, refresh_expires_at) -> None:
        def op(conn):
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO auth_sessions "
                    "(session_id, tenant_id, user_id, access_token_hash, "
                    "refresh_token_hash, access_token_expires_at, expires_at, status) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,'active')",
                    (session_id, tenant_id, user_id, access_token_hash,
                     refresh_token_hash, access_expires_at, refresh_expires_at),
                )
            conn.commit()
        self._pool.run(op)

    def _by_hash(self, column: str, token_hash: str) -> SessionRecord | None:
        if column not in ("access_token_hash", "refresh_token_hash"):
            raise ValueError("非法 token 列")
        def op(conn):
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT tenant_id, session_id, user_id, access_token_expires_at, "
                    "expires_at, status FROM auth_sessions "
                    f"WHERE {column}=%s AND status='active' LIMIT 1",
                    (token_hash,),
                )
                row = cur.fetchone()
            if row is None:
                return None
            return SessionRecord(
                tenant_id=row["tenant_id"], session_id=row["session_id"],
                user_id=row["user_id"], expires_at=row["expires_at"],
                access_expires_at=row.get("access_token_expires_at"),
                status=row["status"],
            )
        return self._pool.run(op)

    @mysql_errors
    def find_by_access_hash(self, access_token_hash: str) -> SessionRecord | None:
        return self._by_hash("access_token_hash", access_token_hash)

    @mysql_errors
    def find_by_refresh_hash(self, refresh_token_hash: str) -> SessionRecord | None:
        return self._by_hash("refresh_token_hash", refresh_token_hash)

    @mysql_errors
    def revoke(self, tenant_id: str, session_id: str) -> None:
        def op(conn):
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE auth_sessions SET status='revoked' "
                    "WHERE tenant_id=%s AND session_id=%s AND status='active'",
                    (tenant_id, session_id),
                )
            conn.commit()
        self._pool.run(op)