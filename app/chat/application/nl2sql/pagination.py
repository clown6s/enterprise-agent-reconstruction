"""NL2SQL 结果的 keyset（游标）分页辅助。

设计要点：
- 采用固定排序列（created_at DESC, order_id DESC）保证排序稳定且唯一。
- 游标以不透明字符串返回，包含游标值、页大小和查询指纹签名，防篡改、防跨查询/跨租户复用。
- 游标值通过可替换 marker 占位并最终作为 DB-API 参数绑定，绝不拼接进 SQL 文本。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
from typing import Any

import sqlglot
from sqlglot import exp

# 固定分页排序列：(列名, 方向)。空时表示不分页。
PAGE_SORT_COLUMNS: tuple[tuple[str, str], ...] = (
    ("created_at", "desc"),
    ("order_id", "desc"),
)

_CURSOR_MARKER = re.compile(r"__NL2SQL_CURSOR_(\d+)__")
_CURSOR_VERSION = 1
_SIGNATURE_LEN = 16


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


def decode_cursor(token: str | None) -> tuple[tuple[Any, ...], int, str] | None:
    """校验并解码游标；签名不匹配返回 None。"""
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
            or not isinstance(fingerprint, str):
        return None
    return tuple(cursor), page_size, fingerprint


def _json_scalar(value: Any) -> Any:
    """把游标值转成可 JSON 编码的标量。"""
    if hasattr(value, "isoformat"):  # datetime / date
        return value.isoformat()
    if isinstance(value, (str, int, float)):
        return value
    return str(value)


def _keyset_condition(tree: exp.Select, markers: list[str]) -> exp.Expression:
    """为固定排序列构造 keyset WHERE（均按 DESC）。"""
    (col0, _), (col1, _) = PAGE_SORT_COLUMNS
    v0_lower = exp.column(markers[0])
    v0_tie = exp.column(markers[1])
    v1 = exp.column(markers[2])
    c0 = exp.column(col0)
    c1 = exp.column(col1)
    # created_at < v0  OR  (created_at = v0 AND order_id < v1)
    lower = exp.LT(this=c0, expression=v0_lower)
    tie = exp.And(
        this=exp.EQ(this=c0, expression=v0_tie),
        expression=exp.LT(this=c1, expression=v1),
    )
    return exp.Or(this=lower, expression=tie)


def apply_pagination(sql: str, *, page_size: int | None, cursor: str | None,
                     fingerprint: str) -> tuple[str, tuple[str, ...], tuple[Any, ...], int] | None:
    """在基础 SQL 上附加稳定排序、keyset 条件和 LIMIT。

    返回 (改后sql, cursor_markers, cursor_params, effective_page_size)，
    当 page_size 为空或 SQL 无法安全改写时返回 None（表示不分页）。
    cursor_markers 是占位标识符，最终由执行器在行策略重写后替换为 %s 并绑定参数。
    """
    if not page_size or page_size < 1:
        return None
    page_size = min(int(page_size), 100)
    sort_values: tuple[Any, ...] = ()
    decoded = decode_cursor(cursor)
    if cursor is not None and decoded is None:
        # 游标无法校验（被篡改/失效）——视为第一页重新开始，避免脏游标导致异常。
        cursor = None
    if cursor is not None and decoded is not None:
        values, cursor_page_size, cursor_fp = decoded
        if cursor_fp != fingerprint:
            # 游标属于其他查询/租户，强制第一页。
            cursor = None
        else:
            sort_values = values
            page_size = min(cursor_page_size, page_size)

    try:
        tree = sqlglot.parse_one(sql, read="mysql")
    except Exception:
        return None
    if not isinstance(tree, exp.Select):
        # 聚合/UNION 等暂不在此处分页，保持原样。
        return None

    markers = [
        "__NL2SQL_CURSOR_0__", "__NL2SQL_CURSOR_1__", "__NL2SQL_CURSOR_2__",
    ]
    if sort_values:
        tree = tree.where(_keyset_condition(tree, markers))
    # 强制稳定排序：覆盖式设置排序列。
    tree = tree.order_by(
        exp.Ordered(this=exp.column(PAGE_SORT_COLUMNS[0][0]), desc=True),
        exp.Ordered(this=exp.column(PAGE_SORT_COLUMNS[1][0]), desc=True),
    )
    tree = tree.limit(page_size + 1)

    try:
        paginated = tree.sql(dialect="mysql")
    except Exception:
        return None
    cursor_params: tuple[Any, ...] = ()
    if sort_values:
        cursor_params = (sort_values[0], sort_values[0], sort_values[1])
    return paginated, tuple(markers), cursor_params, page_size
