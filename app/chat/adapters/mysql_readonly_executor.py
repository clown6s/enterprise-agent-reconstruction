"""NL2SQL 的只读 MySQL 执行器适配器。"""
import uuid

import pymysql

from ..application.nl2sql.row_rewrite import rewrite_with_row_policies
from ..application.nl2sql.tenant_rewrite import assert_readonly
from ..application.ports import ReadonlySqlExecutor
from ..domain.models import SqlResult


class MysqlReadonlyExecutor(ReadonlySqlExecutor):
    def __init__(self, *, host: str, port: int = 3306, user: str,
                 password: str, database: str, connect_timeout: float = 10.0):
        self._config = dict(host=host, port=int(port), user=user, password=password,
                            database=database, charset="utf8mb4",
                            connect_timeout=connect_timeout,
                            cursorclass=pymysql.cursors.Cursor,
                            autocommit=False)

    def query(self, sql: str, *, timeout_s: float = 10.0,
              max_rows: int = 1000, row_policies=()) -> SqlResult:
        """执行单条只读查询，并在数据库会话中施加时间限制。"""
        assert_readonly(sql)
        if timeout_s <= 0:
            raise ValueError("查询超时必须为正数")
        if max_rows < 1:
            raise ValueError("最大返回行数必须为正数")
        sql, params = self._apply_row_policies(sql, row_policies)
        timeout_ms = max(1, int(timeout_s * 1000))
        config = dict(self._config, read_timeout=timeout_s,
                      write_timeout=timeout_s)
        connection = pymysql.connect(**config)
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET SESSION TRANSACTION READ ONLY")
                cursor.execute("SET SESSION MAX_EXECUTION_TIME = %s", (timeout_ms,))
                if params:
                    cursor.execute(sql, params)
                else:
                    cursor.execute(sql)
                description = cursor.description or ()
                columns = tuple(item[0] for item in description)
                rows = tuple(tuple(row) for row in cursor.fetchmany(max_rows))
            connection.rollback()
            return SqlResult(columns=columns, rows=rows,
                             query_id=str(uuid.uuid4()), row_count=len(rows))
        finally:
            connection.close()

    @staticmethod
    def _apply_row_policies(sql: str, row_policies) -> tuple[str, tuple]:
        """把绑定后的谓词组合为带参数的派生表。

        受管控的物理表（已登记任意行权限策略）会经 AST 重写为带过滤条件的
        派生表；不支持的形态直接拒绝执行，而不是返回未受管控的 SQL。
        空输入保留原有的无策略快路径。
        """
        if not row_policies:
            return sql, ()
        return rewrite_with_row_policies(sql, row_policies)
