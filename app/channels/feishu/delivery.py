"""飞书投递记录与幂等适配器，基于已建 feishu_deliveries 表。"""
import hashlib

from app.chat.adapters.mysql_pool import MysqlPool, mysql_errors


class MysqlFeishuDeliveryStore:
    def __init__(self, pool: MysqlPool):
        self._pool = pool

    @mysql_errors
    def enqueue(self, *, tenant_id: str, idempotency_key: str, event_id: str,
                message_id: str, receive_id: str, receive_id_type: str,
                message_type: str, payload: str) -> None:
        def op(conn):
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT IGNORE INTO feishu_deliveries "
                    "(tenant_id,idempotency_key,event_id,message_id,receive_id,"
                    "receive_id_type,message_type,payload_hash,payload_json,status) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'pending')",
                    (tenant_id, idempotency_key, event_id, message_id, receive_id,
                     receive_id_type, message_type,
                     hashlib.sha256(payload.encode()).hexdigest(), payload),
                )
            conn.commit()
        self._pool.run(op)

    @mysql_errors
    def mark(self, *, tenant_id: str, idempotency_key: str, status: str,
             error_code: str | None = None) -> None:
        if status not in {"pending", "sending", "succeeded", "retrying", "failed", "cancelled"}:
            raise ValueError("非法飞书投递状态")
        def op(conn):
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE feishu_deliveries SET status=%s,last_error_code=%s,"
                    "sent_at=IF(%s='succeeded',CURRENT_TIMESTAMP(6),sent_at),"
                    "updated_at=CURRENT_TIMESTAMP(6) "
                    "WHERE tenant_id=%s AND idempotency_key=%s",
                    (status, error_code, status, tenant_id, idempotency_key),
                )
            conn.commit()
        self._pool.run(op)

    def close(self) -> None:
        self._pool.close()
