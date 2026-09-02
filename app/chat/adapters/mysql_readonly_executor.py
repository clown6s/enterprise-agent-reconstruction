"""Read-only MySQL executor adapter for NL2SQL."""
import re
import uuid

import pymysql

from ..application.nl2sql.sql_guard import is_policy_safe
from ..application.ports import ReadonlySqlExecutor
from ..domain.exceptions import SqlPolicyError
from ..domain.models import SqlResult

# Literals and quoted identifiers, replaced with same-length spaces so keyword
# positions in the original SQL are preserved for safe WHERE injection.
_QUOTED = re.compile(r"'[^']*'|\"[^\"]*\"|`[^`]*`")
_WHERE = re.compile(r"\bwhere\b", re.I)
_CLAUSE_BOUNDARY = re.compile(r"\b(GROUP\s+BY|ORDER\s+BY|HAVING|LIMIT|FOR\s+UPDATE)\b", re.I)


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
        # The SQL guard is mandatory at this boundary too, even if callers bypass service.
        if not re.match(r"^\s*select\b", sql, re.I):
            raise ValueError("只读执行器仅允许 SELECT")
        sql, params = self._apply_row_policies(sql, row_policies)
        connection = pymysql.connect(**self._config)
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET SESSION TRANSACTION READ ONLY")
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
        """Combine bound predicates into the WHERE clause with parameters.

        Row policies are only applied to a simple single-table SELECT; any
        other shape fails closed rather than risking a misplaced predicate.
        """
        if not row_policies:
            return sql, ()
        if not is_policy_safe(sql):
            raise SqlPolicyError("行级权限无法安全应用于复杂 SQL")
        predicate = " AND ".join(f"({p.sql})" for p in row_policies)
        params = tuple(value for p in row_policies for value in p.params)
        return MysqlReadonlyExecutor._inject_predicate(sql, predicate), params

    @staticmethod
    def _mask(sql: str) -> str:
        return _QUOTED.sub(lambda m: " " * len(m.group(0)), sql)

    @staticmethod
    def _inject_predicate(sql: str, predicate: str) -> str:
        masked = MysqlReadonlyExecutor._mask(sql)
        where = _WHERE.search(masked)
        if where:
            insert_at = where.end()
            following = re.match(r"\s*", sql[insert_at:])
            insert_at += following.end()
            return sql[:insert_at] + predicate + " AND " + sql[insert_at:]
        boundary = _CLAUSE_BOUNDARY.search(masked)
        if boundary:
            pos = boundary.start()
            return sql[:pos] + " WHERE " + predicate + " " + sql[pos:].strip()
        return (sql.strip() + " WHERE " + predicate).strip()
