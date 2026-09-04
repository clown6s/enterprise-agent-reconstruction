"""不依赖外部 SQL 解析器的保守只读 SQL 策略校验。

这是纵深防御的一层，而不是唯一防线：执行器还会使用专用只读账号，
并限制返回行数、执行时间和扫描范围。

表白名单校验严格：SQL 引用的每张表（FROM、JOIN、逗号分隔的表列表）
都必须位于白名单中。单个允许的表不能再覆盖查询其他位置引用的未授权表。
"""
import re

from ...domain.exceptions import SqlPolicyError
from .tenant_rewrite import assert_readonly

try:  # sqlglot 支撑列白名单校验
    import sqlglot
    from sqlglot import exp as _exp
except Exception as _sqlglot_err:  # pragma: no cover - 可选依赖
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
    re.compile(r";\s*[a-zA-Z]"),          # 多条语句
    re.compile(r"--"),                    # SQL 注释
    re.compile(r"/\*"),                   # 块注释
    re.compile(r"\binto\s+outfile\b", re.I),
    re.compile(r"\binto\s+dumpfile\b", re.I),
    re.compile(r"\bselect\s+\*", re.I),   # 禁止 select *
)

# 表引用：一个（可选带 schema 前缀的）标识符，
# 紧跟 FROM / JOIN 或表列表中的逗号之后。
_STRIPPED = re.compile(r"'[^']*'|\"[^\"]*\"|`[^`]*`")
_SCHEMA_QUALIFIED = re.compile(r"^[A-Za-z_][\w$]*\.[A-Za-z_][\w$]*$")
_CLAUSE_KEYWORD = re.compile(
    r"\b(WHERE|GROUP\s+BY|ORDER\s+BY|HAVING|LIMIT|OFFSET|"
    r"JOIN|LEFT\s+JOIN|RIGHT\s+JOIN|INNER\s+JOIN|CROSS\s+JOIN|"
    r"UNION|ON|AND|OR|SET|VALUES|RETURNING)\b", re.I)
# 将单个表位置拆分为 [schema.]table + 可选别名，
# 而不消费尾随的子句关键字。
_FROM_TABLE = re.compile(
    r"(?P<name>[A-Za-z_][\w$]*(?:\.[A-Za-z_][\w$]*)?)"
    r"(?:\s+(?:AS\s+)?(?P<alias>[A-Za-z_][\w$]*))?"
    r"(?=\s*(?:WHERE|GROUP\s+BY|ORDER\s+BY|HAVING|LIMIT|OFFSET|"
    r"JOIN|LEFT\s+JOIN|RIGHT\s+JOIN|INNER\s+JOIN|CROSS\s+JOIN|"
    r"UNION|,|\)|$))", re.I)


def _strip_literals(sql: str) -> str:
    """把字符串字面量替换为空格，避免字面量内部被误当作表引用。"""
    return _STRIPPED.sub(" ", sql)


def _cte_names(sql: str) -> set[str]:
    """收集 WITH ... AS (...) 形式 CTE 引入的表名。

    CTE 名称是局部定义的别名，不是物理表，因而不能当作未授权引用处理。
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
    """去掉 schema 限定前缀：``db.orders`` -> ``orders``。"""
    return name.split(".")[-1].lower()


def _referenced_tables(sql: str) -> set[str]:
    """从 FROM/JOIN 子句启发式地提取物理表引用。

    只有出现在 FROM/JOIN 表列表作用域内的标识符才被视为表。列列表和函数
    参数不会被扫描，因此 ``SELECT MAX(amount) FROM orders`` 不会把
    ``amount`` 误当作表。
    """
    stripped = _strip_literals(sql)
    tables: set[str] = set()
    for m in re.finditer(
            r"\b(?:FROM|JOIN|LEFT\s+JOIN|RIGHT\s+JOIN|INNER\s+JOIN|"
            r"CROSS\s+JOIN)\b", stripped, re.I):
        tail = stripped[m.end():]
        end = _CLAUSE_KEYWORD.search(tail)
        scope = tail[:end.start()] if end else tail
        # 在顶层逗号处拆分表列表，但忽略任何
        # 仍位于函数/表达式内部的片段（例如带调用的 JOIN ON）。
        for piece in scope.split(","):
            fm = _FROM_TABLE.match(piece.strip())
            if fm and not re.search(r"\(", piece):
                tables.add(_bare_table(fm.group("name")))
    return tables


def referenced_tables(sql: str) -> set[str]:
    """对外暴露一条 SELECT 引用的物理表。"""
    return _referenced_tables(sql)


def _parse_select_trees(sql: str) -> list:
    """把去除字面量后的 SQL 解析为恰好一条 SELECT 的 AST（MySQL 方言）。

    拒绝多条语句输入；``row_rewrite`` 已依赖同一解析器，因此这里引入一个
    轻量依赖是合理的。结尾多余的 ``;`` 会被去掉，以免触发 sqlglot 对
    “单条语句”的要求。
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
    """收集该 SELECT 投影暴露为输出别名的名称。

    ``SUM(amount) AS total_amount`` 登记的是 ``total_amount``（而非
    ``amount``）；裸列 ``region`` 也会登记 ``region``，以便 ``ORDER BY
    region`` 能被解析。这些并非物理列，因此在 GROUP/ORDER/HAVING 中被引用时
    不得按表白名单校验。
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
    """判断 ``col`` 是否为对 SELECT 输出别名的无限定引用。

    仅在 GROUP BY / ORDER BY / HAVING 中成立（这些位置能看见 SELECT 别名）。
    在 WHERE / JOIN ON / SELECT 列表本身里，同名标识符是物理列，必须校验。
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
    """拒绝引用不在各表白名单中的列。

    使用 sqlglot AST 递归遍历每个 SELECT 分支（JOIN、CTE、子查询、UNION）。
    限定列解析到物理表；未限定列在所有允许表的并集中解析，避免合法的同名列
    被误报。派生表或 CTE 别名绑定的列已在虚拟来源内部受保护，这里也会再次
    校验。GROUP/ORDER/HAVING 中引用的 SELECT 输出别名不参与校验。
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
        # 虚拟来源将列作为别名暴露，而非作为
        # 物理表：CTE 名称和派生表（Subquery）别名。
        # 表自身的 ALIAS 是物理的，绝不能视为虚拟。
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

        physical: dict[str, str] = {}  # 可用名称/别名 -> 规范表键
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
    """判断单表 SELECT 是否可以安全追加行级策略。

    多表（JOIN/逗号分隔）、UNION、子查询和 CTE 结构会被拒绝，避免行级条件
    被错误应用到不对应的数据行。
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
    assert_readonly(sql)
    # 关键字检查前先剔除字符串字面量，避免业务文本中的单词被误判为写关键字。
    stripped = _strip_literals(sql).lower()
    for keyword in _BLOCKED_KEYWORDS:
        if re.search(rf"\b{keyword}\b", stripped):
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
    if allowed_columns is not None:
        # fail-closed：只要启用了列白名单，SQL 引用的每张物理表都必须有对应
        # 的已登记列白名单；缺任一表即拒绝，避免"整表未登记列"导致列校验
        # 被整体跳过（此前 allowed_columns 为空时放行，LLM 可编造任意列名）。
        normalized_cols = {str(k).lower() for k in allowed_columns}
        ctes = _cte_names(sql)
        for ref in _referenced_tables(sql):
            if ref not in ctes and ref not in normalized_cols:
                raise SqlPolicyError(f"表 {ref} 未登记列白名单，拒绝执行")
        _validate_allowed_columns(_parse_select_trees(sql), allowed_columns)
    return sql
