"""Read-only MySQL executor adapter for NL2SQL."""
import re
import uuid

import pymysql

from ..application.ports import ReadonlySqlExecutor
from ..domain.exceptions import LlmError
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
              max_rows: int = 1000) -> SqlResult:
        # The SQL guard is mandatory at this boundary too, even if callers bypass service.
        if not re.match(r"^\s*select\b", sql, re.I):
            raise ValueError("只读执行器仅允许 SELECT")
        connection = pymysql.connect(**self._config)
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET SESSION TRANSACTION READ ONLY")
                cursor.execute(sql)
                description = cursor.description or ()
                columns = tuple(item[0] for item in description)
                rows = tuple(tuple(row) for row in cursor.fetchmany(max_rows))
            connection.rollback()
            return SqlResult(columns=columns, rows=rows,
                             query_id=str(uuid.uuid4()), row_count=len(rows))
        finally:
            connection.close()
