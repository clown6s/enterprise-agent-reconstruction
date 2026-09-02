"""Layered tests for row-policy catalog resolution and SQL execution."""
from collections import OrderedDict

import pytest

from app.chat.adapters.mysql_schema_catalog import MysqlSchemaCatalog
from app.chat.application.context import RequestContext
from app.chat.application.nl2sql.row_policy import BoundPolicy
from app.chat.domain.exceptions import ValidationError, SqlPolicyError


class Cursor:
    def __init__(self, sink):
        self.sink = sink
        self.last = None
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def execute(self, sql, params=None):
        self.sink.calls.append((sql, params))
        normalized = " ".join(sql.split()).lower()
        self.last = None
        for needle, value in self.sink.plan.items():
            if needle.lower() in normalized:
                self.last = value
                break
    def fetchone(self): return self.last
    def fetchall(self): return self.last or []

class Conn:
    def __init__(self, sink): self.sink = sink
    def cursor(self): return Cursor(self.sink)

class Pool:
    def __init__(self, plan):
        self.sink = type("Sink", (), {"plan": OrderedDict(plan), "calls": []})()
    def run(self, fn, *args, **kwargs): return fn(Conn(self.sink), *args, **kwargs)


def ctx(**kwargs):
    return RequestContext(tenant_id="t1", user_id="u1", authenticated=True, **kwargs)


def test_catalog_matches_user_role_and_department_and_binds_context():
    pool = Pool([
        ("SELECT domain_id FROM sql_data_domains", {"domain_id": "d1"}),
        ("SELECT subject_type, subject_id, row_predicate_template, allowed", [
            {"subject_type": "user", "subject_id": "u1",
             "row_predicate_template": "owner_id = :user_id", "allowed": 1},
            {"subject_type": "role", "subject_id": "finance",
             "row_predicate_template": "tenant_id = :tenant_id", "allowed": 1},
            {"subject_type": "department", "subject_id": "dep1",
             "row_predicate_template": "department_id IN :department_ids", "allowed": 1},
        ]),
    ])
    policies = MysqlSchemaCatalog(pool).row_policies(
        "orders", "orders", context=ctx(roles=("finance",), department_ids=("dep1", "dep2")))
    assert [p.sql for p in policies] == [
        "owner_id = %s", "tenant_id = %s", "department_id IN (%s, %s)"]
    assert [p.params for p in policies] == [("u1",), ("t1",), ("dep1", "dep2")]
    assert pool.sink.calls[-1][1] == ("t1", "d1", "orders", "u1", "finance", "dep1", "dep2")


def test_catalog_deny_wins_over_matching_allows():
    pool = Pool([
        ("SELECT domain_id FROM sql_data_domains", {"domain_id": "d1"}),
        ("SELECT subject_type, subject_id, row_predicate_template, allowed", [
            {"subject_type": "role", "subject_id": "finance",
             "row_predicate_template": "1=1", "allowed": 1},
            {"subject_type": "user", "subject_id": "u1",
             "row_predicate_template": "1=1", "allowed": 0},
        ]),
    ])
    with pytest.raises(ValidationError):
        MysqlSchemaCatalog(pool).row_policies("orders", "orders", context=ctx(roles=("finance",)))


def test_catalog_without_matching_policy_is_empty():
    pool = Pool([
        ("SELECT domain_id FROM sql_data_domains", {"domain_id": "d1"}),
        ("SELECT subject_type, subject_id, row_predicate_template, allowed", []),
    ])
    assert MysqlSchemaCatalog(pool).row_policies("orders", "orders", context=ctx()) == ()


def test_bound_policy_shape_is_executor_friendly():
    p = BoundPolicy("owner_id = %s", ("u1",))
    assert p.sql.endswith("%s") and p.params == ("u1",)


def test_executor_policy_injection_and_binding(monkeypatch):
    from app.chat.adapters import mysql_readonly_executor as module
    class Cursor:
        description = [("amount",)]
        def __init__(self): self.executed = []
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def execute(self, sql, params=None): self.executed.append((sql, params))
        def fetchmany(self, n): return [(10,)]
    class Conn:
        def __init__(self): self.cursor_obj = Cursor()
        def cursor(self): return self.cursor_obj
        def rollback(self): pass
        def close(self): pass
    connection = Conn()
    monkeypatch.setattr(module.pymysql, "connect", lambda **kwargs: connection)
    result = module.MysqlReadonlyExecutor(host="h", user="u", password="p", database="d").query(
        "SELECT amount FROM orders WHERE tenant_id = 't1' ORDER BY amount",
        row_policies={"orders": (BoundPolicy("owner_id = %s", ("u1",)),)})
    sql, params = connection.cursor_obj.executed[-1]
    assert "(owner_id = %s)" in sql
    assert "tenant_id = 't1'" in sql
    assert sql.startswith("SELECT amount FROM (")
    assert params == ("u1",)
    assert result.row_count == 1


def test_executor_fails_closed_when_policy_table_is_not_in_sql():
    from app.chat.adapters.mysql_readonly_executor import MysqlReadonlyExecutor
    with pytest.raises(SqlPolicyError):
        MysqlReadonlyExecutor._apply_row_policies(
            "SELECT amount FROM orders",
            {"customers": (BoundPolicy("owner_id = %s", ("u1",)),)})
