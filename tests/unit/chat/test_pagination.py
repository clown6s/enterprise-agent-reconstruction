"""NL2SQL 游标分页的单元测试。"""
from datetime import datetime

from app.chat.application.nl2sql.pagination import (
    apply_pagination,
    decode_cursor,
    encode_cursor,
    query_fingerprint,
)
from app.chat.adapters.mysql_readonly_executor import MysqlReadonlyExecutor
from app.chat.domain.models import SqlResult


def test_cursor_round_trip_and_tamper_rejection():
    fingerprint = query_fingerprint(
        tenant_id="tenant-1", domain="orders", base_sql="SELECT amount FROM orders"
    )
    token = encode_cursor(
        (datetime(2026, 1, 2, 3, 4, 5), 42), page_size=20,
        fingerprint=fingerprint,
    )

    values, page_size, actual_fingerprint = decode_cursor(token)
    assert values == ("2026-01-02T03:04:05", 42)
    assert page_size == 20
    assert actual_fingerprint == fingerprint
    assert decode_cursor(token[:-1] + ("0" if token[-1] != "0" else "1")) is None


def test_apply_pagination_adds_keyset_condition_and_limit():
    fingerprint = query_fingerprint(
        tenant_id="tenant-1", domain="orders", base_sql="SELECT created_at, order_id FROM orders"
    )
    first = apply_pagination(
        "SELECT created_at, order_id FROM orders",
        page_size=20, cursor=None, fingerprint=fingerprint,
    )
    assert first is not None
    sql, markers, params, effective_size = first
    assert "ORDER BY created_at DESC, order_id DESC" in sql
    assert "LIMIT 21" in sql
    # 首页无 keyset 条件：marker 不会出现在 SQL 中，参数为空。
    assert markers == ("__NL2SQL_CURSOR_0__", "__NL2SQL_CURSOR_1__", "__NL2SQL_CURSOR_2__")
    assert "__NL2SQL_CURSOR_0__" not in sql
    assert "__NL2SQL_CURSOR_1__" not in sql
    assert params == ()
    assert effective_size == 20

    token = encode_cursor(("2026-01-02T03:04:05", 42), page_size=20,
                          fingerprint=fingerprint)
    second = apply_pagination(
        "SELECT created_at, order_id FROM orders",
        page_size=20, cursor=token, fingerprint=fingerprint,
    )
    assert second is not None
    sql, markers, params, effective_size = second
    assert markers == ("__NL2SQL_CURSOR_0__", "__NL2SQL_CURSOR_1__", "__NL2SQL_CURSOR_2__")
    assert params == ("2026-01-02T03:04:05", "2026-01-02T03:04:05", 42)
    assert "LIMIT 21" in sql
    assert "__NL2SQL_CURSOR_0__" in sql
    assert "__NL2SQL_CURSOR_1__" in sql
    assert effective_size == 20


def test_executor_reports_extra_row_as_truncated(monkeypatch):
    class _Cursor:
        description = (("created_at",), ("order_id",))

        def __init__(self):
            self.executed = []

        def execute(self, sql, params=None):
            self.executed.append((sql, params))

        def fetchmany(self, size):
            assert size == 21
            return [("2026-01-02", i) for i in range(21)]

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class _Connection:
        def __init__(self):
            self.cursor_obj = _Cursor()

        def cursor(self):
            return self.cursor_obj

        def rollback(self):
            pass

        def close(self):
            pass

    connection = _Connection()
    monkeypatch.setattr("pymysql.connect", lambda **kwargs: connection)
    result = MysqlReadonlyExecutor(
        host="localhost", user="u", password="p", database="d"
    ).query(
        "SELECT created_at, order_id FROM orders LIMIT 21",
        max_rows=20,
    )
    assert result.row_count == 20
    assert len(result.rows) == 20
    assert result.truncated is True


def test_executor_binds_row_policy_before_cursor_parameters(monkeypatch):
    class _Cursor:
        description = (("created_at",), ("order_id",))

        def __init__(self):
            self.calls = []

        def execute(self, sql, params=None):
            self.calls.append((sql, params))

        def fetchmany(self, size):
            return [("2026-01-02", 1)]

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class _Connection:
        def __init__(self):
            self.cursor_obj = _Cursor()

        def cursor(self):
            return self.cursor_obj

        def rollback(self):
            pass

        def close(self):
            pass

    connection = _Connection()
    monkeypatch.setattr("pymysql.connect", lambda **kwargs: connection)
    result = MysqlReadonlyExecutor(
        host="localhost", user="u", password="p", database="d"
    ).query(
        "SELECT created_at, order_id FROM orders "
        "WHERE created_at < __NL2SQL_CURSOR_0__ LIMIT 21",
        max_rows=20,
        row_policies={},
        cursor_markers=("__NL2SQL_CURSOR_0__",),
        cursor_params=("2026-01-03",),
    )
    assert result.row_count == 1
    query_calls = [call for call in connection.cursor_obj.calls if call[1] is not None]
    assert query_calls[-1][1] == ("2026-01-03",)
    assert "%s" in query_calls[-1][0]
