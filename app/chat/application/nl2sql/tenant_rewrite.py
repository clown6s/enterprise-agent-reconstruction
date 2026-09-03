"""基于 SQL AST 的租户过滤与只读语句校验。"""
from __future__ import annotations

import sqlglot
from sqlglot import exp

from ...domain.exceptions import SqlPolicyError

_WRITE_NODES = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Create,
    exp.Drop,
    exp.Alter,
    exp.Merge,
    exp.Command,
)


def assert_readonly(sql: str) -> str:
    """校验输入是单条只读 SELECT，并允许 WITH 查询。"""
    if not isinstance(sql, str) or not sql.strip():
        raise SqlPolicyError("SQL 为空")
    try:
        statements = sqlglot.parse(sql.rstrip().rstrip(";"), read="mysql")
    except Exception as exc:
        raise SqlPolicyError("SQL 无法解析，已拒绝执行") from exc
    if len(statements) != 1:
        raise SqlPolicyError("只允许单条 SELECT 查询")
    tree = statements[0]
    if not isinstance(tree, (exp.Select, exp.Union)):
        raise SqlPolicyError("只允许 SELECT 查询")
    if any(isinstance(node, _WRITE_NODES) for node in tree.walk()):
        raise SqlPolicyError("只允许只读 SELECT 查询")
    return sql.strip().rstrip(";").strip()


def physical_tables(sql: str) -> set[str]:
    """提取 SQL 引用的物理表名（排除 CTE 名称与派生表虚拟来源）。"""
    try:
        tree = sqlglot.parse_one(sql, read="mysql")
    except Exception as exc:
        raise SqlPolicyError("SQL 无法解析，已拒绝执行") from exc
    cte_names = {
        cte.alias_or_name.lower()
        for cte in tree.find_all(exp.CTE)
        if cte.alias_or_name
    }
    tables: set[str] = set()
    for table in tree.find_all(exp.Table):
        if table.name.lower() not in cte_names:
            tables.add(table.name.lower())
    return tables
