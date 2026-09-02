"""Conservative read-only SQL policy enforcement without an external SQL parser.

This is defense-in-depth, not the only layer: the executor also runs on a
dedicated read-only account with row/time/scan limits.

Table allowlisting is strict: every table referenced by the SQL (FROM, JOIN,
comma lists) must be in the allowlist. A single allowed table can no longer
"cover" an unrelated unauthorized table referenced elsewhere in the query.
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
    re.compile(r"\bselect\s+\*", re.I),   # no select *
)

# A table reference: an (optionally schema-qualified) identifier that
# immediately follows FROM / JOIN or a comma in a table list.
_STRIPPED = re.compile(r"'[^']*'|\"[^\"]*\"|`[^`]*`")
_SCHEMA_QUALIFIED = re.compile(r"^[A-Za-z_][\w$]*\.[A-Za-z_][\w$]*$")
_CLAUSE_KEYWORD = re.compile(
    r"\b(WHERE|GROUP\s+BY|ORDER\s+BY|HAVING|LIMIT|OFFSET|"
    r"JOIN|LEFT\s+JOIN|RIGHT\s+JOIN|INNER\s+JOIN|CROSS\s+JOIN|"
    r"UNION|ON|AND|OR|SET|VALUES|RETURNING)\b", re.I)
# Splits a single table position into [schema.]table + optional alias,
# without consuming the trailing clause keyword.
_FROM_TABLE = re.compile(
    r"(?P<name>[A-Za-z_][\w$]*(?:\.[A-Za-z_][\w$]*)?)"
    r"(?:\s+(?:AS\s+)?(?P<alias>[A-Za-z_][\w$]*))?"
    r"(?=\s*(?:WHERE|GROUP\s+BY|ORDER\s+BY|HAVING|LIMIT|OFFSET|"
    r"JOIN|LEFT\s+JOIN|RIGHT\s+JOIN|INNER\s+JOIN|CROSS\s+JOIN|"
    r"UNION|,|\)|$))", re.I)


def _strip_literals(sql: str) -> str:
    """Replace string literals with spaces so table refs are not matched inside them."""
    return _STRIPPED.sub(" ", sql)


def _cte_names(sql: str) -> set[str]:
    """Collect table names introduced by WITH ... AS (...) CTEs.

    CTE names are locally-defined aliases, not physical tables, so they must
    not be treated as unauthorized references.
    """
    names: set[str] = set()
    for m in re.finditer(r"\bWITH\b(?:\s+RECURSIVE\b)?\s*"
                         r"((?:[A-Za-z_][\w$]*\s*(?:\([^)]*\))?\s*,\s*)*"
                         r"[A-Za-z_][\w$]*\s*(?:\([^)]*\))?)\s+AS\s*\(", sql, re.I):
        chunk = m.group(1)
        for name in re.findall(r"[A-Za-z_][\w$]*", chunk):
            names.add(name.lower())
    return names


def _bare_table(name: str) -> str:
    """Strip a schema qualifier: ``db.orders`` -> ``orders``."""
    return name.split(".")[-1].lower()


def _referenced_tables(sql: str) -> set[str]:
    """Heuristically extract physical table references from FROM/JOIN clauses.

    Only identifiers that appear inside a FROM/JOIN table-list scope are
    treated as tables. Column lists and function arguments are not scanned, so
    ``SELECT MAX(amount) FROM orders`` does not turn ``amount`` into a table.
    """
    stripped = _strip_literals(sql)
    tables: set[str] = set()
    for m in re.finditer(
            r"\b(?:FROM|JOIN|LEFT\s+JOIN|RIGHT\s+JOIN|INNER\s+JOIN|"
            r"CROSS\s+JOIN)\b", stripped, re.I):
        tail = stripped[m.end():]
        end = _CLAUSE_KEYWORD.search(tail)
        scope = tail[:end.start()] if end else tail
        # Split the table list on top-level commas, but ignore any segment that
        # is still inside a function/expression (e.g. a JOIN ON with a call).
        for piece in scope.split(","):
            fm = _FROM_TABLE.match(piece.strip())
            if fm and not re.search(r"\(", piece):
                tables.add(_bare_table(fm.group("name")))
    return tables


def referenced_tables(sql: str) -> set[str]:
    """Publicly expose the physical tables referenced by a SELECT."""
    return _referenced_tables(sql)


_POLICY_UNSAFE = re.compile(r"\bunion\b|\(\s*select\b|\bwith\b", re.I)


def is_policy_safe(sql: str) -> bool:
    """True when a single-table SELECT can be safely augmented with row policies.

    Multi-table (JOIN/comma), UNION, subquery and CTE shapes are rejected so a
    row predicate cannot be applied to the wrong rows.
    """
    return len(_referenced_tables(sql)) == 1 and not _POLICY_UNSAFE.search(sql)


def validate_sql(sql: str, *, allowed_tables: set[str] | None = None,
                 blocked_columns: dict[str, set[str]] | None = None,
                 max_length: int = 4000) -> str:
    if not isinstance(sql, str) or not sql.strip():
        raise SqlPolicyError("SQL 为空")
    sql = sql.strip().rstrip(";").strip()
    if len(sql) > max_length:
        raise SqlPolicyError(f"SQL 过长（{len(sql)} > {max_length}）")
    lower = sql.lower()
    # 允许只读 CTE，但最终语句必须是 SELECT；写操作仍由关键字检查拒绝。
    if not re.match(r"^\s*(?:with\b[\s\S]*\)\s*)?select\b", sql, re.I):
        raise SqlPolicyError("只允许 SELECT 查询")
    for keyword in _BLOCKED_KEYWORDS:
        if re.search(rf"\b{keyword}\b", lower):
            raise SqlPolicyError(f"禁止关键字: {keyword}")
    for pattern in _FORBIDDEN_PATTERNS:
        if pattern.search(sql):
            raise SqlPolicyError("SQL 包含被禁止的模式")
    if allowed_tables is not None:
        if not allowed_tables:
            raise SqlPolicyError("未配置任何允许的表")
        allowed = {t.lower() for t in allowed_tables}
        ctes = _cte_names(sql)
        refs = _referenced_tables(sql)
        if not refs:
            raise SqlPolicyError("SQL 未引用任何表")
        unauthorized = sorted(
            ref for ref in refs if ref not in allowed and ref not in ctes)
        if unauthorized:
            raise SqlPolicyError(
                f"SQL 引用了未授权表: {', '.join(unauthorized)}")
    if blocked_columns:
        blocked = {col.lower() for cols in blocked_columns.values() for col in cols}
        if blocked:
            stripped = _strip_literals(sql)
            for ident in re.findall(r"[A-Za-z_][\w$]*", stripped):
                if ident.lower() in blocked:
                    raise SqlPolicyError(f"SQL 引用了敏感字段: {ident}")
    return sql
