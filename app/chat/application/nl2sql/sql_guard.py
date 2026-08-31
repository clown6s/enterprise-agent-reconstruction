"""Conservative read-only SQL policy enforcement without an external SQL parser.

This is defense-in-depth, not the only layer: the executor also runs on a
dedicated read-only account with row/time/scan limits.
"""
import re

from ...domain.exceptions import SqlPolicyError

_BLOCKED_KEYWORDS = (
    "insert", "update", "delete", "drop", "alter", "truncate", "create",
    "grant", "revoke", "call", "exec", "merge", "replace",
)
_FORBIDDEN_PATTERNS = (
    re.compile(r";\s*[a-zA-Z]"),          # multi-statement
    re.compile(r"--"),                    # comment
    re.compile(r"/\*"),                   # block comment
    re.compile(r"\binto\s+outfile\b", re.I),
    re.compile(r"\binto\s+dumpfile\b", re.I),
    re.compile(r"\bselect\s+\*"),         # no select *
)


def validate_sql(sql: str, *, allowed_tables: set[str] | None = None,
                 max_length: int = 4000) -> str:
    if not isinstance(sql, str) or not sql.strip():
        raise SqlPolicyError("SQL 为空")
    sql = sql.strip().rstrip(";").strip()
    if len(sql) > max_length:
        raise SqlPolicyError(f"SQL 过长（{len(sql)} > {max_length}）")
    lower = sql.lower()
    if not lower.startswith("select"):
        raise SqlPolicyError("只允许 SELECT 查询")
    for keyword in _BLOCKED_KEYWORDS:
        if re.search(rf"\b{keyword}\b", lower):
            raise SqlPolicyError(f"禁止关键字: {keyword}")
    for pattern in _FORBIDDEN_PATTERNS:
        if pattern.search(sql):
            raise SqlPolicyError("SQL 包含被禁止的模式")
    if allowed_tables is not None:
        for table in allowed_tables:
            if re.search(rf"\b{re.escape(table)}\b", sql, re.I):
                break
        else:
            raise SqlPolicyError("SQL 未引用任何允许的表")
    return sql
