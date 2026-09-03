"""Conservative read-only SQL policy enforcement without an external SQL parser.

This is defense-in-depth, not the only layer: the executor also runs on a
dedicated read-only account with row/time/scan limits.

Table allowlisting is strict: every table referenced by the SQL (FROM, JOIN,
comma lists) must be in the allowlist. A single allowed table can no longer
"cover" an unrelated unauthorized table referenced elsewhere in the query.
"""
import re

from ...domain.exceptions import SqlPolicyError

try:  # sqlglot backs column-allowlist validation
    import sqlglot
    from sqlglot import exp as _exp
except Exception as _sqlglot_err:  # pragma: no cover - optional dependency
    sqlglot = None
    _exp = None
    _SQLGLOT_ERROR = _sqlglot_err
else:
    _SQLGLOT_ERROR = None

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


def _parse_select_trees(sql: str) -> list:
    """Parse literal-stripped SQL into exactly one SELECT AST (MySQL dialect).

    Rejects multi-statement inputs; ``row_rewrite`` already depends on the same
    parser, so a thin dependency is fine here. A trailing ``;`` is trimmed so
    it does not trip sqlglot's "single statement" need.
    """
    if sqlglot is None or _exp is None:
        raise SqlPolicyError("SQL 解析器不可用，无法进行列级校验")
    source = re.sub(r";\s*$", "", sql)
    try:
        statements = sqlglot.parse(source, read="mysql")
    except Exception as exc:
        raise SqlPolicyError("SQL 无法解析，已拒绝执行") from exc
    if len(statements) != 1:
        raise SqlPolicyError("只允许单条 SELECT 查询")
    return [statements[0]]


def _collect_output_aliases(tree) -> set[str]:
    """Names exposed as output aliases by this SELECT's projection.

    ``SUM(amount) AS total_amount`` registers ``total_amount`` (not
    ``amount``); a bare ``region`` also registers ``region`` so that
    ``ORDER BY region`` resolves. These are NOT physical columns and must not
    be validated against the table allowlist when referenced in GROUP/ORDER/
    HAVING.
    """
    aliases: set[str] = set()
    for select in tree.find_all(_exp.Select):
        for expr in getattr(select, "expressions", ()) or ():
            name = None
            if isinstance(expr, _exp.Alias):
                name = getattr(expr, "alias", None)
            elif isinstance(expr, _exp.Column):
                name = getattr(expr, "name", None)
            if name:
                aliases.add(str(name).lower())
    return aliases


def _is_output_alias_reference(col, output_aliases: set[str]) -> bool:
    """True when ``col`` is an unqualified reference to a SELECT output alias.

    Only valid inside GROUP BY / ORDER BY / HAVING (where SELECT aliases are
    visible). In WHERE / JOIN ON / the SELECT list itself the same identifier
    is a physical column and must be validated.
    """
    name = str(getattr(col, "name", "") or "").lower()
    if name not in output_aliases:
        return False
    node = getattr(col, "parent", None)
    while node is not None and not isinstance(node, _exp.Select):
        if isinstance(node, (_exp.Order, _exp.Ordered, _exp.Group, _exp.Having)):
            return True
        node = getattr(node, "parent", None)
    return False


def _validate_allowed_columns(trees: list, allowed_columns) -> None:
    """Reject column references not present in the per-table allowlist.

    Recursively walks every SELECT branch (JOIN, CTE, subquery, UNION) with the
    sqlglot AST. Qualified columns resolve to a physical table; unqualified
    columns resolve against the union of every allowed table so a legitimately
    ambiguous name is not a false positive. Columns bound to a derived table /
    CTE alias are already guarded inside that virtual source and asserted here.
    SELECT output aliases referenced in GROUP/ORDER/HAVING are exempt.
    """
    normalized = {}
    for table, cols in allowed_columns.items():
        key = str(table).lower()
        allowed = {str(c).lower() for c in cols} if cols else set()
        if key not in normalized:
            normalized[key] = set()
        normalized[key].update(allowed)
    if not normalized:
        return

    all_allowed: set[str] = set()
    for cols in normalized.values():
        all_allowed.update(cols)

    for tree in trees:
        # Virtual sources that expose their columns as aliases rather than as a
        # physical table: CTE names and derived-table (Subquery) aliases. A
        # Table's own ALIAS is physical and must NOT be treated virtual.
        virtual: set[str] = set()
        for cte in tree.find_all(_exp.CTE):
            alias = cte.alias if hasattr(cte, "alias") else None
            if alias is not None:
                virtual.add(str(alias).lower())
        for alias in tree.find_all(_exp.TableAlias):
            if isinstance(getattr(alias, "parent", None), _exp.Subquery):
                name = getattr(alias, "name", None)
                if name:
                    virtual.add(str(name).lower())

        physical: dict[str, str] = {}  # usable name/alias -> canonical table key
        for table in tree.find_all(_exp.Table):
            name = str(getattr(table, "name", "") or "").lower()
            if not name or name in virtual:
                continue
            physical.setdefault(name, name)
            table_alias = getattr(table, "alias", None)
            if table_alias:
                physical.setdefault(str(table_alias).lower(), name)

        output_aliases = _collect_output_aliases(tree)
        for col in tree.find_all(_exp.Column):
            qualifier = getattr(col, "table", None)
            column_name = str(getattr(col, "name", "") or "").lower()
            q = str(qualifier).lower() if qualifier else ""
            if q in virtual:
                continue
            # SELECT 输出别名（如 SUM(amount) AS total_amount）只能在
            # ORDER BY / GROUP BY / HAVING 中引用，不应当作物理列校验；
            # WHERE / JOIN ON / SELECT 列表内出现的同名标识符仍是物理列。
            if not q and _is_output_alias_reference(col, output_aliases):
                continue
            base = physical.get(q) if q else None
            if base is not None:
                if column_name not in normalized.get(base, set()):
                    raise SqlPolicyError(
                        f"表 {base} 引用了未授权字段: {column_name}")
            elif column_name not in all_allowed:
                raise SqlPolicyError(f"引用了未授权字段: {column_name}")


_POLICY_UNSAFE = re.compile(r"\bunion\b|\(\s*select\b|\bwith\b", re.I)


def is_policy_safe(sql: str) -> bool:
    """True when a single-table SELECT can be safely augmented with row policies.

    Multi-table (JOIN/comma), UNION, subquery and CTE shapes are rejected so a
    row predicate cannot be applied to the wrong rows.
    """
    return len(_referenced_tables(sql)) == 1 and not _POLICY_UNSAFE.search(sql)


def validate_sql(sql: str, *, allowed_tables: set[str] | None = None,
                 allowed_columns: dict[str, set[str]] | None = None,
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
    if allowed_columns is not None and allowed_columns:
        _validate_allowed_columns(_parse_select_trees(sql), allowed_columns)
    return sql
