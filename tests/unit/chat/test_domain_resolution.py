"""Memory 与 MySQL 域解析合同测试：共享同一套评分/歧义语义。"""
import pytest

from app.chat.adapters.memory_schema_catalog import MemorySchemaCatalog, SchemaDomain
from app.chat.application.nl2sql.domain_resolution import resolve_domain


def _catalog(domains):
    return MemorySchemaCatalog([
        SchemaDomain(name, desc, frozenset({name}), keywords)
        for name, desc, keywords in domains
    ])


def test_single_domain_hit():
    cat = _catalog([("orders", "订单", ("订单",))])
    assert cat.resolve_domain("统计订单金额") == "orders"


def test_no_domain_is_none():
    cat = _catalog([("orders", "订单", ("订单",))])
    assert cat.resolve_domain("平均值是什么意思") is None


def test_ambiguous_domains_is_none():
    # “金额”同时被订单、采购命中且分差不明显 → 歧义，返回 None。
    cat = _catalog([
        ("orders", "订单", ("订单", "金额")),
        ("procurement", "采购", ("采购", "金额")),
    ])
    assert cat.resolve_domain("查询本月金额") is None


def test_dominant_domain_wins_ambiguity():
    # 订单命中“订单+金额”两词，得分明显高于仅命中“金额”的采购域 → 唯一。
    cat = _catalog([
        ("orders", "订单", ("订单", "金额")),
        ("procurement", "采购", ("采购",)),
    ])
    assert cat.resolve_domain("查询本月订单金额") == "orders"


def test_shared_resolver_matches_mysql_margin_rule():
    # 直接验证共享函数的 margin 语义：第二名×1.3 仍小于第一名才返回。
    assert resolve_domain("查询订单金额", {
        "orders": [("订单", 1.0), ("金额", 1.0)],
        "procurement": [("金额", 1.0)],
    }) == "orders"
    assert resolve_domain("金额", {
        "orders": [("金额", 1.0)],
        "procurement": [("金额", 1.0)],
    }) is None
