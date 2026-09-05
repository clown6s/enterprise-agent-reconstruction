"""NL2SQL 结果的 keyset（游标）分页辅助。

设计要点：
- 分页计划由调用方按数据域构建，排序列可带物理表/别名限定，从而支持 JOIN，
  不再全局写死某两列。
- 游标以不透明字符串返回，包含游标值、页大小和查询指纹签名，防篡改、防跨查询/跨租户复用。
- 游标值通过可替换 marker 占位并最终作为 DB-API 参数绑定，绝不拼接进 SQL 文本。
- 对畸形/越界游标做严格校验并明确拒绝，不静默回退到第一页。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
from dataclasses import dataclass
from typing import Any

import sqlglot
from sqlglot import exp

from ...domain.exceptions import SqlPolicyError

_CURSOR_MARKER = re.compile(r"__NL2SQL_CURSOR_(\d+)__")
_CURSOR_VERSION = 2
_SIGNATURE_LEN = 16
# 分页排序键上限，避免构造爆炸式 keyset 条件。
_MAX_SORT_KEYS = 4


@dataclass(frozen=True)
class SortKey:
    """单个排序键；table 用于对 JOIN 限定列来源，None 表示裸列。"""
    column: str
    direction: str = "desc"
    table: str | None = None

    @property
    def qualified(self) -> str:
        return f"{self.table}.{self.column}" if self.table else self.column


@dataclass(frozen=True)
class PaginationPlan:
    """一次查询的分页计划。sort_keys 决定 keyset 与游标字段。"""
    sort_keys: tuple[SortKey, ...]
    page_size: int = 5


def _secret() -> bytes:
    """分页游标签名密钥；生产环境应通过环境变量注入。"""
    return os.getenv("NL2SQL_CURSOR_SECRET", "dev-only-cursor-secret").encode("utf-8")


def query_fingerprint(*, tenant_id: str, domain: str, base_sql: str) -> str:
    """对"租户 + 数据域 + 基础 SQL"做指纹，防止游标跨查询或跨租户复用。"""
    material = f"{tenant_id}\x00{domain}\x00{base_sql}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def encode_cursor(sort_values: tuple[Any, ...], *, page_size: int,
                  fingerprint: str) -> str:
    """把游标值、页大小和指纹编码为带签名的不透明字符串。"""
    payload = {
        "v": _CURSOR_VERSION,
        "c": [_json_scalar(v) for v in sort_values],
        "ps": int(page_size),
        "fp": fingerprint,
    }
    body = base64.urlsafe_b64encode(
        json.dumps(payload, ensure_ascii=False).encode("utf-8"),
    ).decode("ascii")
    sig = hmac.new(_secret(), body.encode("ascii"),
                   hashlib.sha256).hexdigest()[:_SIGNATURE_LEN]
    return f"{body}.{sig}"


def decode_cursor(token: str | None, *, expected_values: int | None = None
                  ) -> tuple[tuple[Any, ...], int, str] | None:
    """校验并解码游标；签名不匹配或结构非法返回 None。

    ``expected_values`` 给定排序键个数时，会校验游标值数量一致，杜绝越界访问。
    """
    if not token or not isinstance(token, str):
        return None
    if "." not in token:
        return None
    body, sig = token.rsplit(".", 1)
    expect = hmac.new(_secret(), body.encode("ascii"),
                      hashlib.sha256).hexdigest()[:_SIGNATURE_LEN]
    if not hmac.compare_digest(sig, expect):
        return None
    try:
        payload = json.loads(base64.urlsafe_b64decode(body.encode("ascii")))
    except Exception:
        return None
    if not isinstance(payload, dict) or payload.get("v") != _CURSOR_VERSION:
        return None
    cursor = payload.get("c")
    page_size = payload.get("ps")
    fingerprint = payload.get("fp")
    if not isinstance(cursor, list) or not isinstance(page_size, int) \
            or not isinstance(fingerprint, str) or page_size < 1:
        return None
    if expected_values is not None and len(cursor) != expected_values:
        return None
    return tuple(cursor), page_size, fingerprint


def _json_scalar(value: Any) -> Any:
    """把游标值转成可 JSON 编码的标量。"""
    if hasattr(value, "isoformat"):  # datetime / date
        return value.isoformat()
    if isinstance(value, (str, int, float)):
        return value
    return str(value)


def _table_alias(tree: exp.Select, table: str) -> str | None:
    """返回给定物理表在查询中使用的别名；未用别名或找不到时返回 None。"""
    table_l = table.lower()
    for t in tree.find_all(exp.Table):
        if str(t.name or "").lower() == table_l:
            alias = getattr(t, "alias", None)
            if alias:
                return str(alias)
            return None
    return None


def _column_expression(tree: exp.Select, key: SortKey) -> exp.Column:
    """构造带可选表限定的列表达式。"""
    qualifier = None
    if key.table:
        qualifier = _table_alias(tree, key.table) or key.table
    return exp.column(key.column, table=qualifier)


def _qualified_column(tree: exp.Select, key: SortKey) -> str:
    """根据 JOIN 场景返回排序列的限定名称。"""
    if key.table:
        return f"{_table_alias(tree, key.table) or key.table}.{key.column}"
    return key.column


def _keyset_condition(tree: exp.Select, keys: tuple[SortKey, ...],
                      markers: list[str]) -> tuple[exp.Expression, list[str]]:
    """按多排序列（默认 DESC）构造 keyset WHERE，逐层消耗 markers。

    返回 (表达式, 已消耗的 markers)。markers 顺序即参数绑定顺序。
    """
    n = len(keys)
    col_refs = [_column_expression(tree, k) for k in keys]
    used: list[str] = []

    def take() -> str:
        m = markers[len(used)]
        used.append(m)
        return m

    # 逐层：(c0 < v0) OR (c0=v0 AND c1 < v1) OR (c0=v0 AND c1=v1 AND c2 < v2) ...
    or_branches = []
    for depth in range(n):
        branch = []
        for i in range(depth):
            # 前导等值条件
            branch.append(exp.EQ(this=col_refs[i], expression=exp.column(take())))
        # 该层严格比较，方向由排序方向决定。
        value = exp.column(take())
        if keys[depth].direction.lower() == "asc":
            branch.append(exp.GT(this=col_refs[depth], expression=value))
        else:
            branch.append(exp.LT(this=col_refs[depth], expression=value))
        or_branches.append(exp.and_(*branch) if len(branch) > 1 else branch[0])
    cond = or_branches[0]
    for b in or_branches[1:]:
        cond = exp.or_(cond, b)
    return cond, used


def apply_pagination(sql: str, *, plan: PaginationPlan | None = None,
                     page_size: int | None = None, cursor: str | int | None = None,
                     offset: int | None = None, fingerprint: str
                     ) -> tuple[str, tuple[str, ...], tuple[Any, ...], int] | None:
    """在基础 SQL 上附加稳定排序、keyset 条件和 LIMIT。

    返回 (改后sql, cursor_markers, cursor_params, effective_page_size)，
    当 plan 为空、page_size 非法或 SQL 无法安全改写时返回 None（表示不分页）。
    cursor_markers 是占位标识符，最终由执行器在行策略重写后替换为 %s 并绑定参数。
    """
    if plan is None and page_size is not None:
        plan = PaginationPlan((SortKey("created_at"), SortKey("order_id")), page_size)
    if plan is None or not plan.sort_keys:
        return None
    if page_size is not None:
        plan = PaginationPlan(plan.sort_keys, page_size)
    if plan.page_size < 1:
        return None
    keys = plan.sort_keys[: _MAX_SORT_KEYS]
    page_size = min(int(plan.page_size), 100)
    if offset is None:
        offset = 0
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise SqlPolicyError("分页位置无效")
    if cursor is not None:
        raise SqlPolicyError("不支持外部游标，请使用下一页或上一页")

    try:
        tree = sqlglot.parse_one(sql, read="mysql")
    except Exception:
        return None
    if not isinstance(tree, exp.Select):
        # 聚合/UNION 等暂不在此处分页。
        return None

    markers: list[str] = []
    used_markers: list[str] = []
    # 排序：保留模型原业务排序，仅在结尾补充稳定 tie-breaker，避免覆盖业务语义。
    order = tree.args.get("order")
    existing = list(order.expressions or []) if order is not None else []
    for k in keys:
        existing.append(exp.Ordered(
            this=_column_expression(tree, k),
            desc=(k.direction.lower() != "asc"),
        ))
    tree = tree.order_by(*existing)
    tree = tree.limit(page_size + 1).offset(offset)

    try:
        paginated = tree.sql(dialect="mysql")
    except Exception:
        return None
    return paginated, tuple(used_markers), (), page_size
