"""飞书事件持久化幂等适配器。"""
from app.chat.adapters.mysql_pool import MysqlPool, mysql_errors


class MysqlFeishuIdempotencyStore:
    def __init__(self, pool: MysqlPool):
        self._pool = pool

    @mysql_errors
    def claim(self, *, tenant_id: str, event_id: str, message_id: str,
              event_type: str) -> bool:
        def op(conn):
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT IGNORE INTO feishu_event_seen "
                    "(tenant_id,event_id,message_id,event_type,status) "
                    "VALUES (%s,%s,%s,%s,'processing')",
                    (tenant_id, event_id, message_id, event_type),
                )
                inserted = cur.rowcount == 1
            conn.commit()
            return inserted
        return self._pool.run(op)

    @mysql_errors
    def mark(self, *, tenant_id: str, event_id: str, status: str,
             error_code: str | None = None) -> None:
        if status not in {"received", "processing", "succeeded", "failed"}:
            raise ValueError("非法飞书事件状态")
        def op(conn):
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE feishu_event_seen SET status=%s,error_code=%s,"
                    "processed_at=IF(%s IN ('succeeded','failed'),CURRENT_TIMESTAMP(6),processed_at) "
                    "WHERE tenant_id=%s AND event_id=%s",
                    (status, error_code, status, tenant_id, event_id),
                )
            conn.commit()
        self._pool.run(op)

    def close(self) -> None:
        self._pool.close()
