"""Unit tests for the Schema Registry MVP (service + MySQL adapter)."""
import json
from collections import OrderedDict

import pytest

from app.chat.adapters.mysql_schema_registry import MysqlSchemaRegistry
from app.chat.application.context import RequestContext
from app.chat.application.schema_registry import (
    SchemaColumn, SchemaDomain, SchemaJoin, SchemaRegistry, SchemaTable,
)
from app.chat.domain.exceptions import ValidationError

_ADMIN = RequestContext(tenant_id="t", user_id="u", authenticated=True,
                        permissions=("schema:admin",))
_CTX = RequestContext(tenant_id="t", user_id="u", authenticated=True)


class _FakeCursor:
    def __init__(self, sink):
        self._sink = sink
        self._last = None

    def __enter__(self): return self
    def __exit__(self, *a): return False

    def execute(self, sql, params=None):
        self._sink.calls.append((sql, params))
        self._sink.last_sql = sql; self._sink.last_params = params
        norm = " ".join(sql.split()).lower()
        self._last = None
        for frag, reply in self._sink.plan.items():
            if " ".join(frag.split()).lower() in norm:
                self._last = reply; break

    def executemany(self, sql, params):
        self._sink.calls.append((sql, params))
        self._last = None

    @property
    def rowcount(self): return self._sink.rowcount
    def fetchone(self): return self._last
    def fetchall(self): return self._last or []


class _FakeConn:
    def __init__(self, sink): self._sink = sink
    def cursor(self): return _FakeCursor(self._sink)
    def commit(self): self._sink.commits += 1
    def rollback(self): self._sink.rollbacks += 1
    def close(self): pass


class _FakePool:
    def __init__(self, sink): self._sink = sink
    def run(self, fn, *a, **k): return fn(_FakeConn(self._sink), *a, **k)


def _make_sink():
    return type("Sink", (), {
        "calls": [], "plan": OrderedDict(), "rowcount": 0,
        "commits": 0, "rollbacks": 0, "last_sql": None, "last_params": None,
    })()


def _store(sink): return MysqlSchemaRegistry(_FakePool(sink))


def _domain():
    return SchemaDomain(
        domain_id="orders_dom", domain_name="orders", description="订单数据",
        default_time_column="created_at", keywords=("订单", "orders"),
        tables=(SchemaTable("orders", description="订单表", columns=(
            SchemaColumn("amount", "decimal", business_name="金额"),)),))


# --- pure service validation ---

def test_service_register_domain_validates_identifier():
    svc = SchemaRegistry(object())
    with pytest.raises(ValidationError):
        svc.register_domain(SchemaDomain("bad id", "x", "d"), context=_ADMIN)


def test_service_register_columns_validates_identifiers():
    svc = SchemaRegistry(object())
    with pytest.raises(ValidationError):
        svc.register_columns("dom", "tbl", [SchemaColumn("col name", "int")], context=_ADMIN)


def test_service_register_joins_validates_join_type():
    svc = SchemaRegistry(object())
    with pytest.raises(ValidationError):
        svc.register_joins("dom", "tbl", [SchemaJoin("t2", {"a": "b"}, "CROSS")], context=_ADMIN)


# --- adapter permission gate ---

def test_adapter_requires_schema_admin_permission():
    sink = _make_sink()
    store = _store(sink)
    with pytest.raises(ValidationError):
        store.publish("dom", context=_CTX)  # no schema:admin
    assert sink.calls == []


def test_adapter_requires_authenticated_context():
    sink = _make_sink()
    store = _store(sink)
    with pytest.raises(ValidationError):
        store.introspect(context=RequestContext())


# --- introspect ---

def test_introspect_filters_identifiers_and_builds_tables():
    sink = _make_sink()
    sink.plan["SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE"] = [
        {"TABLE_NAME": "orders", "COLUMN_NAME": "amount", "DATA_TYPE": "decimal"},
        {"TABLE_NAME": "orders", "COLUMN_NAME": "created_at", "DATA_TYPE": "datetime"},
    ]
    store = _store(sink)
    result = store.introspect(tables=["orders"], context=_ADMIN)
    assert result == [{"table_name": "orders", "columns": [
        {"column_name": "amount", "data_type": "decimal"},
        {"column_name": "created_at", "data_type": "datetime"}]}]
    assert sink.last_params == ["orders"]


def test_introspect_rejects_bad_identifier():
    sink = _make_sink(); store = _store(sink)
    with pytest.raises(ValidationError):
        store.introspect(tables=["orders; DROP"], context=_ADMIN)


# --- register + publish flow ---

def test_register_domain_commits_and_upserts():
    sink = _make_sink()
    store = _store(sink)
    store.register_domain(_domain(), context=_ADMIN)
    insert = [s for s, _ in sink.calls if s.startswith("INSERT INTO sql_data_domains")]
    assert len(insert) == 1
    assert sink.last_params[0:3] == ("t", "orders_dom", "orders")
    assert sink.commits == 1
    # keywords written
    assert any(s.startswith("INSERT INTO sql_domain_keywords") for s, _ in sink.calls)


def test_register_table_stores_empty_joins_json():
    sink = _make_sink()
    store = _store(sink)
    store.register_table("dom", SchemaTable("orders"), context=_ADMIN)
    assert sink.last_params[5] == "[]"
    assert sink.commits == 1


def test_register_columns_upserts_all_columns():
    sink = _make_sink()
    store = _store(sink)
    cols = [SchemaColumn("amount", "decimal", business_name="金额"),
            SchemaColumn("created_at", "datetime", business_name="创建时间")]
    store.register_columns("dom", "orders", cols, context=_ADMIN)
    inserts = [s for s, _ in sink.calls if s.startswith("INSERT INTO sql_allowed_columns")]
    assert len(inserts) == 2
    assert sink.commits == 1


def test_register_joins_writes_json_to_allowed_joins():
    sink = _make_sink()
    store = _store(sink)
    store.register_joins("dom", "orders",
                         [SchemaJoin("customers", {"customer_id": "id"}, "LEFT")],
                         context=_ADMIN)
    assert sink.last_params[0] == json.dumps(
        [{"table": "customers", "columns": {"customer_id": "id"}, "join_type": "LEFT"}])
    assert sink.last_params[1:4] == ("t", "dom", "orders")
    assert sink.commits == 1


def test_publish_requires_at_least_one_table():
    sink = _make_sink()
    sink.plan["SELECT 1 FROM sql_data_domains"] = {"1": 1}
    sink.plan["SELECT COUNT(*) AS n FROM sql_allowed_tables"] = {"n": 0}
    store = _store(sink)
    with pytest.raises(ValidationError):
        store.publish("dom", context=_ADMIN)
    assert sink.commits == 0


def test_publish_writes_version_and_change_log():
    sink = _make_sink()
    sink.plan["SELECT domain_name, description, default_time_column, max_rows, max_execution_seconds FROM sql_data_domains"] = {
        "domain_name": "orders", "description": "订单", "default_time_column": "created_at",
        "max_rows": 1000, "max_execution_seconds": 10}
    sink.plan["SELECT table_name, table_description, required_tenant_filter, allowed_joins FROM sql_allowed_tables"] = [
        {"table_name": "orders", "table_description": "订单表", "required_tenant_filter": 1,
         "allowed_joins": json.dumps([{"table": "customers", "columns": {"customer_id": "id"}, "join_type": "LEFT"}])}]
    sink.plan["SELECT column_name, business_name, data_type, selectable, filterable, sortable, aggregatable, `sensitive`, masking_rule, description FROM sql_allowed_columns"] = [
        {"column_name": "amount", "business_name": "金额", "data_type": "decimal", "selectable": 1,
         "filterable": 1, "sortable": 0, "aggregatable": 1, "sensitive": 0,
         "masking_rule": None, "description": None}]
    sink.plan["SELECT COALESCE(MAX(version_no), 0) AS n FROM sql_schema_versions"] = {"n": 0}
    store = _store(sink)
    result = store.publish("dom", context=_ADMIN, version=None, reason="首次发布")
    assert result["version_no"] == 1
    assert result["snapshot_hash"]
    update = [p for s, p in sink.calls if s.startswith("UPDATE sql_data_domains")]
    assert len(update) == 1
    assert update[0] == ("u", "t", "dom")
    assert any(s.startswith("INSERT INTO sql_schema_versions") for s, _ in sink.calls)
    assert any(s.startswith("INSERT INTO sql_schema_change_logs") for s, _ in sink.calls)
    assert any(s.startswith("INSERT INTO sql_allowed_joins") for s, _ in sink.calls)
    assert sink.commits == 1


def test_publish_rejects_invalid_version():
    sink = _make_sink()
    sink.plan["SELECT domain_name, description, default_time_column, max_rows, max_execution_seconds FROM sql_data_domains"] = {
        "domain_name": "orders", "description": "订单", "default_time_column": None,
        "max_rows": 1000, "max_execution_seconds": 10}
    sink.plan["SELECT table_name, table_description, required_tenant_filter, allowed_joins FROM sql_allowed_tables"] = [
        {"table_name": "orders", "table_description": "订单表", "required_tenant_filter": 1, "allowed_joins": None}]
    sink.plan["SELECT column_name, business_name, data_type, selectable, filterable, sortable, aggregatable, `sensitive`, masking_rule, description FROM sql_allowed_columns"] = []
    sink.plan["SELECT COALESCE(MAX(version_no), 0) AS n FROM sql_schema_versions"] = {"n": 0}
    store = _store(sink)
    with pytest.raises(ValidationError):
        store.publish("dom", context=_ADMIN, version="abc")
    assert sink.commits == 0


def test_publish_rejects_unknown_domain():
    sink = _make_sink()
    sink.plan["SELECT domain_name, description, default_time_column, max_rows, max_execution_seconds FROM sql_data_domains"] = None
    store = _store(sink)
    with pytest.raises(ValidationError):
        store.publish("dom", context=_ADMIN)


# --- row policy admin ---

_POLICY = SchemaRegistryPortPolicyRow()


def _policy():
    from app.chat.application.schema_registry import RowPolicyRegistration
    return RowPolicyRegistration(
        table_name="orders", subject_type="role", subject_id="finance",
        predicate_template="department_id IN :department_ids", allowed=True)


def test_service_register_row_policy_invalid_subject_type():
    from app.chat.application.schema_registry import RowPolicyRegistration
    svc = SchemaRegistry(object())
    with pytest.raises(ValidationError):
        svc.register_row_policy("dom", RowPolicyRegistration(
            "orders", "group", "g1", "department_id = :department_ids"), context=_ADMIN)


def test_service_register_row_policy_rejects_unsafe_template():
    from app.chat.application.schema_registry import RowPolicyRegistration
    svc = SchemaRegistry(object())
    with pytest.raises(ValidationError):
        svc.register_row_policy("dom", RowPolicyRegistration(
            "orders", "user", "u1", "owner_id = :unknown_placeholder"), context=_ADMIN)


def test_adapter_register_row_policy_commits():
    from app.chat.application.schema_registry import RowPolicyRegistration
    sink = _make_sink()
    sink.plan["SELECT 1 FROM sql_allowed_tables"] = {"1": 1}
    store = _store(sink)
    store.register_row_policy("dom", _policy(), context=_ADMIN)
    insert = [s for s, _ in sink.calls if s.startswith("INSERT INTO sql_domain_permissions")]
    assert len(insert) == 1
    assert sink.calls[-1][1] == ("t", "dom", "orders", "role", "finance",
                                 "department_id IN :department_ids", True)
    assert sink.commits == 1


def test_adapter_register_row_policy_requires_registered_table():
    sink = _make_sink()
    sink.plan["SELECT 1 FROM sql_allowed_tables"] = None
    store = _store(sink)
    with pytest.raises(ValidationError):
        store.register_row_policy("dom", _policy(), context=_ADMIN)
    assert sink.commits == 0


def test_adapter_list_row_policies_tenant_scoped():
    sink = _make_sink()
    sink.plan["SELECT permission_id, table_name, subject_type, subject_id, row_predicate_template, allowed, created_at"] = [
        {"permission_id": 1, "table_name": "orders", "subject_type": "user",
         "subject_id": "u1", "row_predicate_template": "owner_id = :user_id",
         "allowed": 1, "created_at": None}]
    rows = _store(sink).list_row_policies("dom", context=_ADMIN)
    assert rows[0]["subject_id"] == "u1"
    assert sink.last_params == ("t", "dom")


def test_adapter_delete_row_policy_commits():
    sink = _make_sink()
    sink.rowcount = 1
    store = _store(sink)
    store.delete_row_policy("dom", 7, context=_ADMIN)
    assert any(s.startswith("DELETE FROM sql_domain_permissions") for s, _ in sink.calls)
    assert sink.last_params == ("t", "dom", 7)
    assert sink.commits == 1
