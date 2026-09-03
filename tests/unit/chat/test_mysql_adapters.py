"""Unit tests for MySQL chat adapters using a fake connection/pool (no DB)."""
import json
from collections import OrderedDict

import pytest

from app.chat.adapters.mysql_conversation_store import MysqlConversationStore
from app.chat.adapters.mysql_schema_catalog import MysqlSchemaCatalog
from app.chat.adapters.mysql_sop_store import MysqlSopStore
from app.chat.domain.exceptions import SopError, ValidationError
from app.chat.domain.models import ChatMessage, SopDefinition, SopExecutionState, SopStep
from app.chat.application.context import RequestContext


_CTX = RequestContext(tenant_id="t", user_id="u", authenticated=True)


class _FakeCursor:
    def __init__(self, sink):
        self._sink = sink
        self._last = None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self._sink.calls.append((sql, params))
        self._sink.last_sql = sql
        self._sink.last_params = params
        normalized = " ".join(sql.split()).lower()
        if "select coalesce(max(seq_no)" in normalized:
            self._last = {"last_seq": self._sink.max_seq}
            return
        self._last = None
        for fragment, reply in self._sink.plan.items():
            if " ".join(fragment.split()).lower() in normalized:
                self._last = reply
                break

    @property
    def rowcount(self):
        return self._sink.rowcount

    def fetchone(self):
        return self._last

    def fetchall(self):
        return self._last or []


class _FakeConn:
    def __init__(self, sink):
        self._sink = sink

    def cursor(self):
        return _FakeCursor(self._sink)

    def commit(self):
        self._sink.commits += 1

    def rollback(self):
        self._sink.rollbacks += 1

    def close(self):
        pass


class _FakePool:
    def __init__(self, sink):
        self._sink = sink

    def run(self, fn, *args, **kwargs):
        return fn(_FakeConn(self._sink), *args, **kwargs)


def _make_sink():
    return type("Sink", (), {
        "calls": [],
        "plan": OrderedDict(),
        "max_seq": 0,
        "rowcount": 0,
        "commits": 0,
        "rollbacks": 0,
        "last_sql": None,
        "last_params": None,
    })()


def _store(cls, sink, **_kwargs):
    pool = _FakePool(sink)
    return cls(pool)


# --- 会话 ---

def test_conversation_get_or_create_inserts_when_missing():
    sink = _make_sink()
    sink.plan["SELECT 1 FROM chat_conversations"] = None
    store = _store(MysqlConversationStore, sink)
    store.get_or_create("c1", context=_CTX)
    inserted = [s for s, _ in sink.calls if s.startswith("INSERT INTO chat_conversations")]
    assert len(inserted) == 1
    assert sink.last_params == ("t", "c1", "u")


def test_conversation_append_increments_seq():
    sink = _make_sink()
    sink.plan["SELECT 1 FROM chat_conversations"] = {"1": 1}
    sink.max_seq = 4
    sink.rowcount = 1
    store = _store(MysqlConversationStore, sink)
    store.append("c1", ChatMessage("user", "hello"), context=_CTX)
    insert = [s for s, _ in sink.calls if s.startswith("INSERT INTO chat_messages")]
    assert len(insert) == 1
    assert sink.last_params == ("t", "c1", 5, "user", "hello")


def test_conversation_recent_params():
    sink = _make_sink()
    sink.plan["SELECT role, content FROM chat_messages"] = []
    store = _store(MysqlConversationStore, sink)
    assert store.recent("c1", limit=10, context=_CTX) == []
    assert sink.last_params == ("t", "c1", 10)


# --- SOP 状态 ---

def test_sop_save_state_optimistic_lock_ok():
    sink = _make_sink()
    sink.rowcount = 1
    # SELECT ... FOR UPDATE 返回已有行以触发 UPDATE 路径
    sink.plan["SELECT execution_id, version_no FROM sop_execution_states"] = {
        "execution_id": "e-1", "version_no": 3}
    store = _store(MysqlSopStore, sink)
    state = SopExecutionState("sop-1", "v1", "s2", {"a": 1}, ("s1",), True)
    store.save_state("conv", state, context=_CTX)
    update = [s for s, _ in sink.calls if s.startswith("UPDATE sop_execution_states")]
    assert len(update) == 1
    # 乐观锁传入 version_no=3
    assert sink.last_params[6] == 3


def test_sop_save_state_optimistic_lock_conflict():
    sink = _make_sink()
    sink.rowcount = 0  # UPDATE 影响 0 行 => 另一个请求抢先了
    sink.plan["SELECT execution_id, version_no FROM sop_execution_states"] = {
        "execution_id": "e-1", "version_no": 3}
    store = _store(MysqlSopStore, sink)
    state = SopExecutionState("sop-1", "v1", "s2", {}, (), False)
    with pytest.raises(SopError):
        store.save_state("conv", state, context=_CTX)


def test_sop_get_state_maps_waiting_confirmation():
    sink = _make_sink()
    sink.plan["SELECT sop_id, sop_version, current_step_id, params_json, completed_steps, execution_status FROM sop_execution_states"] = {
        "sop_id": "sop-1", "sop_version": "v1", "current_step_id": "s3",
        "params_json": '{"k":1}', "completed_steps": '["s1","s2"]',
        "execution_status": "waiting_confirmation"}
    store = _store(MysqlSopStore, sink)
    state = store.get_state("conv", context=_CTX)
    assert state is not None
    assert state.awaiting_confirmation is True


# --- 模式目录 ---

def test_schema_allowed_tables():
    sink = _make_sink()
    sink.plan["SELECT t.table_name, t.domain_id FROM sql_allowed_tables"] = [
        {"table_name": "orders", "domain_id": "d-1"},
        {"table_name": "order_items", "domain_id": "d-1"}]
    store = _store(MysqlSchemaCatalog, sink)
    assert store.allowed_tables("orders", context=_CTX) == {"orders", "order_items"}


def test_schema_allowed_columns():
    sink = _make_sink()
    sink.plan["SELECT domain_id FROM sql_data_domains"] = {"domain_id": "d-1"}
    sink.plan["SELECT table_name, column_name FROM sql_allowed_columns"] = [
        {"table_name": "orders", "column_name": "amount"},
        {"table_name": "orders", "column_name": "region"},
        {"table_name": "customers", "column_name": "name"}]
    store = _store(MysqlSchemaCatalog, sink)
    assert store.allowed_columns("orders", context=_CTX) == {
        "orders": {"amount", "region"},
        "customers": {"name"},
    }


def test_schema_allowed_columns_unknown_domain():
    sink = _make_sink()
    sink.plan["SELECT domain_id FROM sql_data_domains"] = None  # 域不存在
    store = _store(MysqlSchemaCatalog, sink)
    assert store.allowed_columns("orders", context=_CTX) == {}


def test_schema_describe_builds_lines():
    sink = _make_sink()
    sink.plan["SELECT domain_id, description FROM sql_data_domains"] = {
        "domain_id": "d-1", "description": "订单数据"}
    sink.plan["SELECT t.table_name, t.table_description, c.column_name, c.business_name, c.data_type, c.selectable, c.filterable, c.sortable, c.aggregatable FROM sql_allowed_tables t"] = [
        {"table_name": "orders", "table_description": "订单表", "column_name": "amount",
         "business_name": "金额", "data_type": "decimal", "selectable": 1,
         "filterable": 1, "sortable": 0, "aggregatable": 1}]
    store = _store(MysqlSchemaCatalog, sink)
    text = store.describe("orders", context=_CTX)
    assert "订单数据" in text and "amount" in text


def test_schema_describe_renders_registry_join_format():
    sink = _make_sink()
    sink.plan["SELECT domain_id, description FROM sql_data_domains"] = {
        "domain_id": "d-1", "description": "订单数据"}
    sink.plan["SELECT t.table_name, t.table_description, c.column_name, c.business_name, c.data_type, c.selectable, c.filterable, c.sortable, c.aggregatable FROM sql_allowed_tables t"] = [
        {"table_name": "orders", "table_description": "订单表", "column_name": "amount",
         "business_name": "金额", "data_type": "decimal", "selectable": 1,
         "filterable": 1, "sortable": 0, "aggregatable": 1}]
    sink.plan["SELECT table_name, allowed_joins FROM sql_allowed_tables"] = [
        {"table_name": "orders", "allowed_joins": json.dumps(
            [{"table": "customers", "columns": {"customer_id": "id"}, "join_type": "LEFT"}])}]
    store = _store(MysqlSchemaCatalog, sink)
    text = store.describe("orders", context=_CTX)
    assert "LEFT JOIN customers ON orders.customer_id=customers.id" in text


def test_schema_domains_filters_denied_domain():
    sink = _make_sink()
    sink.plan["SELECT domain_id FROM sql_domain_permissions"] = [
        {"domain_id": "d-denied"}]
    sink.plan["SELECT domain_id, domain_name FROM sql_data_domains"] = [
        {"domain_id": "d-ok", "domain_name": "orders"},
        {"domain_id": "d-denied", "domain_name": "secret"}]
    store = _store(MysqlSchemaCatalog, sink)
    assert store.domains(context=_CTX) == ["orders"]


def test_adapters_require_authenticated_context():
    sink = _make_sink()
    from app.chat.domain.exceptions import ValidationError
    store = MysqlConversationStore(_FakePool(sink))
    with pytest.raises(ValidationError):
        store.get_or_create("c1", context=RequestContext())  # 未认证

def test_build_chat_allows_explicit_test_doubles(monkeypatch):
    monkeypatch.setenv("CHAT_STORAGE", "mysql")
    from app.chat.bootstrap.container import build_chat
    from app.chat.adapters.memory_conversation_store import MemoryConversationStore
    from app.chat.adapters.memory_sop_store import MemorySopStore
    from app.chat.adapters.memory_schema_catalog import MemorySchemaCatalog
    from app.chat.bootstrap.defaults import default_sops, default_schema_domains
    class _R:
        def retrieve(self, *a, **k): return []
        def close(self): pass
    svc = build_chat(
        retriever=_R(), conversation=MemoryConversationStore(),
        sop_store=MemorySopStore(default_sops()),
        schema_catalog=MemorySchemaCatalog(default_schema_domains()),
    )
    assert isinstance(svc.conversation, MemoryConversationStore)


def test_mysql_store_does_not_require_process_identity():
    sink = _make_sink()
    store = MysqlConversationStore(_FakePool(sink))
    # 身份按请求提供，不从 CHAT_* 环境变量读取。
    with pytest.raises(ValidationError):
        store.get_or_create("c1", context=RequestContext())
