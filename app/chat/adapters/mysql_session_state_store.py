"""结构化多轮会话状态的 MySQL 持久化实现。"""
import json

from ..application.context import identity
from ..application.ports import SessionStateStore
from ..domain.exceptions import SessionConflictError
from ..domain.models import Intent, SessionState
from .mysql_pool import MysqlPool, mysql_errors


def _state_to_row(state: SessionState) -> dict:
    return {
        "last_intent": state.last_intent.value if state.last_intent else None,
        "last_domain": state.last_domain,
        "last_query_id": state.last_query_id,
        "current_sop_id": state.current_sop_id,
        "current_sop_version": state.current_sop_version,
        "current_step_id": state.current_step_id,
        "state_json": json.dumps(state.extra, ensure_ascii=False),
    }


def _row_to_state(row) -> SessionState:
    extra = json.loads(row["state_json"] or "{}") if row.get("state_json") else {}
    intent = None
    if row.get("last_intent"):
        try:
            intent = Intent(row["last_intent"])
        except ValueError:
            intent = None
    return SessionState(
        last_intent=intent, last_domain=row.get("last_domain"),
        last_query_id=row.get("last_query_id"),
        current_sop_id=row.get("current_sop_id"),
        current_sop_version=row.get("current_sop_version"),
        current_step_id=row.get("current_step_id"),
        extra=extra, version_no=int(row.get("version_no") or 1),
    )


class MysqlSessionStateStore(SessionStateStore):
    def __init__(self, pool: MysqlPool):
        self._pool = pool

    @mysql_errors
    def get(self, conversation_id: str, *, context) -> SessionState | None:
        tenant_id, user_id = identity(context)

        def op(conn):
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT last_intent,last_domain,last_query_id,current_sop_id,"
                    "current_sop_version,current_step_id,state_json,version_no "
                    "FROM chat_session_states "
                    "WHERE tenant_id=%s AND conversation_id=%s AND user_id=%s LIMIT 1",
                    (tenant_id, conversation_id, user_id),
                )
                return cur.fetchone()
        row = self._pool.run(op)
        return _row_to_state(row) if row else None

    @mysql_errors
    def save(self, conversation_id: str, state: SessionState, *, context) -> None:
        tenant_id, user_id = identity(context)
        row = _state_to_row(state)

        def op(conn):
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT version_no FROM chat_session_states "
                    "WHERE tenant_id=%s AND conversation_id=%s AND user_id=%s "
                    "FOR UPDATE", (tenant_id, conversation_id, user_id),
                )
                existing = cur.fetchone()
                if existing is None:
                    cur.execute(
                        "INSERT INTO chat_session_states "
                        "(tenant_id,conversation_id,user_id,last_intent,last_domain,"
                        "last_query_id,current_sop_id,current_sop_version,current_step_id,"
                        "state_json,version_no) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (tenant_id, conversation_id, user_id, row["last_intent"],
                         row["last_domain"], row["last_query_id"], row["current_sop_id"],
                         row["current_sop_version"], row["current_step_id"],
                         row["state_json"], 1),
                    )
                else:
                    cur.execute(
                        "UPDATE chat_session_states SET last_intent=%s,last_domain=%s,"
                        "last_query_id=%s,current_sop_id=%s,current_sop_version=%s,"
                        "current_step_id=%s,state_json=%s,version_no=version_no+1 "
                        "WHERE tenant_id=%s AND conversation_id=%s AND user_id=%s "
                        "AND version_no=%s",
                        (row["last_intent"], row["last_domain"], row["last_query_id"],
                         row["current_sop_id"], row["current_sop_version"],
                         row["current_step_id"], row["state_json"], tenant_id,
                         conversation_id, user_id, int(existing["version_no"])),
                    )
                    if cur.rowcount != 1:
                        raise SessionConflictError("会话状态已被其他请求更新，请重试")
            conn.commit()
        self._pool.run(op)

    def close(self) -> None:
        self._pool.close()