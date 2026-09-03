"""MySQL audit adapter for chat, RAG, SOP and NL2SQL events."""
import hashlib
import json
import uuid

import structlog

from ..application.ports import AuditLogger
from ..domain.models import AuditEvent
from .mysql_pool import MysqlPool, mysql_errors

logger = structlog.get_logger(__name__)


class MysqlAuditLogger(AuditLogger):
    def __init__(self, pool: MysqlPool, *, save_answer: bool = False,
                 sample_rows: int = 5):
        self._pool = pool
        self._save_answer = save_answer
        self._sample_rows = max(0, min(int(sample_rows), 20))

    @mysql_errors
    def record(self, event: AuditEvent) -> None:
        # Require a tenant for durable audit rows; anonymous events remain logs only.
        if not event.tenant_id or not event.user_id:
            logger.warning("audit_event_without_identity", event_id=event.event_id,
                           trace_id=event.trace_id, stage=event.stage)
            return
        payload = dict(event.payload or {})
        stage = event.stage
        if stage == "nl2sql":
            self._record_nl2sql(event, payload)
        elif stage == "rag":
            self._record_rag(event, payload)
        elif stage == "tool":
            self._record_tool(event, payload)
        elif stage == "security":
            self._record_security(event, payload)
        else:
            self._record_chat(event, payload)

    def _run(self, operation):
        self._pool.run(operation)

    def _record_chat(self, event, payload):
        def op(conn):
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO qa_answer_logs "
                    "(log_id,tenant_id,user_id,conversation_id,trace_id,question,mode,status,"
                    "sent_citation_nos,used_citation_nos,unused_citation_nos,grounded,answer) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (event.event_id, event.tenant_id, event.user_id, event.conversation_id,
                     event.trace_id, payload.get("question", ""), event.mode or "",
                     event.status, json.dumps(payload.get("sent", [])),
                     json.dumps(payload.get("used", [])), json.dumps(payload.get("unused", [])),
                     bool(payload.get("grounded", False)),
                     payload.get("answer") if self._save_answer else None),
                )
            conn.commit()
        self._run(op)

    def _record_rag(self, event, payload):
        self._record_chat(event, payload)

    def _record_nl2sql(self, event, payload):
        sql = str(payload.get("sql", ""))
        sql_hash = hashlib.sha256(sql.encode("utf-8")).hexdigest() if sql else None
        def op(conn):
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO nl2sql_audit_logs "
                    "(tenant_id,audit_id,user_id,conversation_id,trace_id,question,"
                    "detected_domain,intent_confidence,generation_status,generated_sql,"
                    "normalized_sql,sql_hash,guard_status,guard_reason,execution_status,"
                    "query_id,row_count,duration_ms,error_code,error_message) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (event.tenant_id, event.event_id, event.user_id, event.conversation_id,
                     event.trace_id, payload.get("question", ""), payload.get("domain"),
                     payload.get("confidence"), payload.get("generation_status", "executed"),
                     sql or None, sql or None, sql_hash, payload.get("guard_status", "allowed"),
                     payload.get("guard_reason"), payload.get("execution_status", "success"),
                     payload.get("query_id"), payload.get("row_count"), payload.get("duration_ms"),
                     payload.get("error_code"), payload.get("error_message")),
                )
            conn.commit()
        self._run(op)

    def _record_tool(self, event, payload):
        def op(conn):
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO chat_tool_calls "
                    "(tenant_id,tool_call_id,user_id,conversation_id,tool_name,arguments_json,"
                    "risk_level,authorization_status,execution_status,result_summary,error_code) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (event.tenant_id, event.event_id, event.user_id, event.conversation_id,
                     payload.get("tool_name", ""), json.dumps(payload.get("arguments", {})),
                     payload.get("risk_level", "low"), payload.get("authorization_status", "allowed"),
                     payload.get("execution_status", "success"),
                     json.dumps(payload.get("result_summary")) if payload.get("result_summary") else None,
                     payload.get("error_code")),
                )
            conn.commit()
        self._run(op)

    def _record_security(self, event, payload):
        def op(conn):
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO security_content_flags "
                    "(tenant_id,content_type,content_ref,risk_level,matched_flags,action_taken,detail) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                    (event.tenant_id, payload.get("content_type", "message"),
                     payload.get("content_ref", event.event_id), payload.get("risk_level", "low"),
                     json.dumps(payload.get("matched_flags", [])), payload.get("action_taken", "allowed"),
                     payload.get("detail")),
                )
            conn.commit()
        self._run(op)

    def close(self) -> None:
        self._pool.close()
