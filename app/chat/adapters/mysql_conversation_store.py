"""聊天会话端口的 MySQL 实现。

存储相对身份是无状态的：租户和用户来自每次请求的 ``context``，因此共享连接池
可以服务多个已认证用户而不会产生跨租户泄露。
"""
from ..application.context import identity
from ..application.ports import ConversationStore
from ..domain.models import ChatMessage
from .mysql_pool import MysqlPool, mysql_errors


class MysqlConversationStore(ConversationStore):
    def __init__(self, pool: MysqlPool):
        self._pool = pool

    @mysql_errors
    def get_or_create(self, conversation_id: str, *, context) -> None:
        tenant_id, user_id = identity(context)

        def operation(conn):
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM chat_conversations "
                    "WHERE tenant_id=%s AND conversation_id=%s AND user_id=%s LIMIT 1",
                    (tenant_id, conversation_id, user_id),
                )
                if cur.fetchone() is None:
                    cur.execute(
                        "INSERT INTO chat_conversations "
                        "(tenant_id, conversation_id, user_id) VALUES (%s,%s,%s)",
                        (tenant_id, conversation_id, user_id),
                    )
            conn.commit()
        self._pool.run(operation)

    @mysql_errors
    def append(self, conversation_id: str, message: ChatMessage, *, context) -> None:
        tenant_id, user_id = identity(context)

        def operation(conn):
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM chat_conversations WHERE tenant_id=%s "
                    "AND conversation_id=%s AND user_id=%s FOR UPDATE",
                    (tenant_id, conversation_id, user_id),
                )
                if cur.fetchone() is None:
                    raise ValueError("会话不存在或不属于当前用户")
                cur.execute(
                    "SELECT COALESCE(MAX(seq_no), 0) AS last_seq FROM chat_messages "
                    "WHERE tenant_id=%s AND conversation_id=%s FOR UPDATE",
                    (tenant_id, conversation_id),
                )
                seq_no = int(cur.fetchone()["last_seq"]) + 1
                cur.execute(
                    "INSERT INTO chat_messages "
                    "(tenant_id, conversation_id, seq_no, role, content) "
                    "VALUES (%s,%s,%s,%s,%s)",
                    (tenant_id, conversation_id, seq_no, message.role, message.content),
                )
            conn.commit()
        self._pool.run(operation)

    @mysql_errors
    def recent(self, conversation_id: str, limit: int = 10, *, context) -> list[ChatMessage]:
        tenant_id, user_id = identity(context)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError("limit 必须为 1 到 100 之间的整数")

        def operation(conn):
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT role, content FROM chat_messages "
                    "WHERE tenant_id=%s AND conversation_id=%s "
                    "ORDER BY seq_no DESC LIMIT %s",
                    (tenant_id, conversation_id, limit),
                )
                rows = cur.fetchall()
            return [ChatMessage(row["role"], row["content"]) for row in reversed(rows)]
        return self._pool.run(operation)

    def close(self) -> None:
        self._pool.close()
