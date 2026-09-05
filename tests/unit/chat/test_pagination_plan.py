"""分页计划与 JOIN 分页的解耦测试。"""
import datetime

from app.chat.application.nl2sql.pagination import (
    PaginationPlan, SortKey, apply_pagination, decode_cursor, encode_cursor,
    query_fingerprint,
)
from app.chat.application.nl2sql.nl2sql_service import Nl2SqlService


def test_plan_driven_qualified_sort():
    fp = query_fingerprint(tenant_id="t", domain="library", base_sql="SELECT b.title,a.author_name FROM books b JOIN book_authors a ON b.author_id=a.author_id")
    plan = PaginationPlan((SortKey("created_at", "desc", "books"),
                           SortKey("book_id", "desc", "books")), page_size=5)
    out = apply_pagination("SELECT b.title,a.author_name FROM books b JOIN book_authors a ON b.author_id=a.author_id", plan=plan, cursor=None, fingerprint=fp)
    assert out is not None
    sql = out[0]
    # 排序列被限定到表别名 b，避免同名列歧义。
    assert "ORDER BY" in sql and ".created_at" in sql
    assert "JOIN book_authors" in sql
    assert "LIMIT 6" in sql


def test_cursor_extra_or_short_values_rejected():
    fp = query_fingerprint(tenant_id="t", domain="orders", base_sql="SELECT x FROM orders")
    plan = PaginationPlan((SortKey("created_at"), SortKey("order_id")), page_size=5)
    # 合法：两值
    tok = encode_cursor(("2026-01-01", "O1"), page_size=5, fingerprint=fp)
    assert apply_pagination("SELECT created_at,order_id FROM orders", plan=plan, cursor=tok, fingerprint=fp) is not None
    # 编码多值但期望两值 → 拒绝
    bad = encode_cursor(("a", "b", "c"), page_size=5, fingerprint=fp)
    import pytest
    from app.chat.domain.exceptions import SqlPolicyError
    with pytest.raises(SqlPolicyError):
        apply_pagination("SELECT created_at,order_id FROM orders", plan=plan, cursor=bad, fingerprint=fp)


def test_cursor_page_size_zero_rejected():
    token = __import__("base64").urlsafe_b64encode(__import__("json").dumps(
        {"v": 2, "c": ["a", "b"], "ps": 0, "fp": "x"}).encode()).decode()
    # 手工构造无签名的畸形 token 应被拒绝
    assert decode_cursor(token, expected_values=2) is None


def test_keyset_params_match_marker_count():
    fp = query_fingerprint(tenant_id="t", domain="orders", base_sql="SELECT x FROM orders")
    plan = PaginationPlan((SortKey("created_at"), SortKey("order_id")), page_size=5)
    tok = encode_cursor(("2026-01-01", "O1"), page_size=5, fingerprint=fp)
    out = apply_pagination("SELECT created_at,order_id FROM orders", plan=plan, cursor=tok, fingerprint=fp)
    _, markers, params, _ = out
    # keyset 两列：3 个 marker、3 个参数；markers 数 == params 数。
    assert len(markers) == len(params) == 3


def test_join_plan_without_config_defaults_disabled():
    """未配置分页域且多表查询，默认关闭分页。"""
    catalog = _NoConfigCatalog()
    llm = _SimpleLLM()
    service = Nl2SqlService(llm, catalog, _NoopExecutor())
    plan = service._pagination_plan("x", "SELECT a.col FROM t1 a JOIN t2 b ON a.id=b.id", {"t1": {"col"}})
    assert plan is None


class _NoConfigCatalog:
    def pagination_config(self, domain, *, context=None): return None
    def allowed_columns(self, domain, *, context=None): return {}


class _NoopExecutor:
    def query(self, *args, **kwargs): raise AssertionError("不应执行")


class _SimpleLLM:
    def __init__(self):
        self.call_count = 0
    def chat(self, messages):
        self.call_count += 1
        return None