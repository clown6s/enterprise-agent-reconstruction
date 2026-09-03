"""SOP 定义、版本和执行状态的 MySQL 实现。

存储相对身份是无状态的：租户和用户来自每次请求的 ``context``，因此共享连接池
可以隔离地服务多个已认证用户。
"""
import json

from ..application.context import identity
from ..application.ports import SopStore
from ..domain.exceptions import SopError
from ..domain.models import SopDefinition, SopExecutionState, SopStep
from .mysql_pool import MysqlPool, mysql_errors


def _tuple_json(value) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return (value,)
    return tuple(str(item) for item in (value or ()))


class MysqlSopStore(SopStore):
    def __init__(self, pool: MysqlPool):
        self._pool = pool

    @mysql_errors
    def find(self, sop_id: str, version: str | None = None, *, context) -> SopDefinition | None:
        tenant_id, _ = identity(context)

        def operation(conn):
            with conn.cursor() as cur:
                if version is None:
                    cur.execute(
                        "SELECT d.sop_id, d.title, d.scope, v.version, v.definition_json "
                        "FROM sop_definitions d JOIN sop_versions v "
                        "ON v.tenant_id=d.tenant_id AND v.sop_id=d.sop_id "
                        "WHERE d.tenant_id=%s AND d.sop_id=%s "
                        "AND d.status='published' AND v.version_status='published' "
                        "ORDER BY v.effective_from DESC, v.version DESC LIMIT 1",
                        (tenant_id, sop_id),
                    )
                else:
                    cur.execute(
                        "SELECT d.sop_id, d.title, d.scope, v.version, v.definition_json "
                        "FROM sop_definitions d JOIN sop_versions v "
                        "ON v.tenant_id=d.tenant_id AND v.sop_id=d.sop_id "
                        "WHERE d.tenant_id=%s AND d.sop_id=%s AND v.version=%s "
                        "AND d.status='published' AND v.version_status='published' LIMIT 1",
                        (tenant_id, sop_id, version),
                    )
                definition = cur.fetchone()
                if definition is None:
                    return None
                cur.execute(
                    "SELECT step_id, sequence_no, instruction, preconditions, inputs, "
                    "next_steps, warnings, requires_confirmation, role_required "
                    "FROM sop_steps WHERE tenant_id=%s AND sop_id=%s AND version=%s "
                    "ORDER BY sequence_no",
                    (tenant_id, sop_id, definition["version"]),
                )
                rows = cur.fetchall()
            return self._definition(definition, rows)
        return self._pool.run(operation)

    @staticmethod
    def _definition(row, steps) -> SopDefinition:
        return SopDefinition(
            sop_id=row["sop_id"], version=row["version"], title=row["title"],
            scope=row.get("scope") or "",
            steps=tuple(SopStep(
                step_id=item["step_id"], sequence=int(item["sequence_no"]),
                instruction=item["instruction"],
                preconditions=_tuple_json(item.get("preconditions")),
                inputs=_tuple_json(item.get("inputs")),
                next_steps=_tuple_json(item.get("next_steps")),
                warnings=_tuple_json(item.get("warnings")),
                requires_confirmation=bool(item.get("requires_confirmation")),
                role_required=item.get("role_required"),
            ) for item in steps),
        )

    @mysql_errors
    def search(self, query: str, *, context) -> list[SopDefinition]:
        tenant_id, _ = identity(context)
        pattern = f"%{query.strip()}%"
        def operation(conn):
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT d.sop_id, d.title, d.scope, v.version, v.definition_json "
                    "FROM sop_definitions d JOIN sop_versions v "
                    "ON v.tenant_id=d.tenant_id AND v.sop_id=d.sop_id "
                    "WHERE d.tenant_id=%s AND d.status='published' "
                    "AND v.version_status='published' AND (d.title LIKE %s OR d.sop_id LIKE %s) "
                    "ORDER BY v.effective_from DESC, v.version DESC",
                    (tenant_id, pattern, pattern),
                )
                definitions = cur.fetchall()
            return [self.find(row["sop_id"], row["version"], context=context) for row in definitions]
        return [item for item in self._pool.run(operation) if item is not None]

    @mysql_errors
    def get_state(self, conversation_id: str, *, context) -> SopExecutionState | None:
        tenant_id, user_id = identity(context)

        def operation(conn):
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT sop_id, sop_version, current_step_id, params_json, "
                    "completed_steps, execution_status FROM sop_execution_states "
                    "WHERE tenant_id=%s AND conversation_id=%s AND user_id=%s "
                    "AND execution_status IN ('active','waiting_input','waiting_confirmation') "
                    "ORDER BY updated_at DESC LIMIT 1",
                    (tenant_id, conversation_id, user_id),
                )
                row = cur.fetchone()
            if row is None:
                return None
            return SopExecutionState(
                sop_id=row["sop_id"], version=row["sop_version"],
                current_step_id=row["current_step_id"],
                params=json.loads(row["params_json"] or "{}"),
                completed_steps=_tuple_json(row["completed_steps"]),
                awaiting_confirmation=(row["execution_status"] == "waiting_confirmation"),
            )
        return self._pool.run(operation)

    @mysql_errors
    def save_state(self, conversation_id: str, state: SopExecutionState, *, context) -> None:
        tenant_id, user_id = identity(context)

        def operation(conn):
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT execution_id, version_no FROM sop_execution_states "
                    "WHERE tenant_id=%s AND conversation_id=%s AND user_id=%s "
                    "AND sop_id=%s AND sop_version=%s AND execution_status IN "
                    "('active','waiting_input','waiting_confirmation') LIMIT 1 FOR UPDATE",
                    (tenant_id, conversation_id, user_id, state.sop_id, state.version),
                )
                row = cur.fetchone()
                params = json.dumps(state.params, ensure_ascii=False)
                completed = json.dumps(state.completed_steps, ensure_ascii=False)
                waiting = "waiting_confirmation" if state.awaiting_confirmation else "active"
                if row is None:
                    cur.execute(
                        "INSERT INTO sop_execution_states "
                        "(tenant_id, execution_id, user_id, conversation_id, sop_id, sop_version, "
                        "current_step_id, execution_status, params_json, completed_steps) "
                        "VALUES (%s,UUID(),%s,%s,%s,%s,%s,%s,%s,%s)",
                        (tenant_id, user_id, conversation_id, state.sop_id,
                         state.version, state.current_step_id, waiting, params, completed),
                    )
                else:
                    cur.execute(
                        "UPDATE sop_execution_states SET current_step_id=%s, execution_status=%s, "
                        "params_json=%s, completed_steps=%s, version_no=version_no+1 "
                        "WHERE tenant_id=%s AND execution_id=%s AND version_no=%s",
                        (state.current_step_id, waiting, params, completed,
                         tenant_id, row["execution_id"], row["version_no"]),
                    )
                    if cur.rowcount != 1:
                        raise SopError("SOP 状态已被其他请求更新，请重试")
            conn.commit()
        self._pool.run(operation)

    def close(self) -> None:
        self._pool.close()
