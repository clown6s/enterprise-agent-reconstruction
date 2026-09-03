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


def inject_tenant_filter(sql: str, tenant_id: str) -> str:
    """为每个物理表包裹认证租户过滤条件。"""
    if not tenant_id:
        raise SqlPolicyError("缺少认证租户，拒绝执行查询")
    try:
        tree = sqlglot.parse_one(sql, read="mysql")
    except Exception as exc:
        raise SqlPolicyError("SQL 无法解析，已拒绝执行") from exc

    cte_names = {
        cte.alias_or_name.lower()
        for cte in tree.find_all(exp.CTE)
        if cte.alias_or_name
    }
    table_nodes = [table for table in tree.find_all(exp.Table)
                   if table.name.lower() not in cte_names]
    if not table_nodes:
        raise SqlPolicyError("未找到可注入租户的物理表，拒绝执行")

    escaped = tenant_id.replace("'", "''")
    predicate = f"tenant_id = '{escaped}'"
    for table in table_nodes:
        original = table.copy()
        original.set("alias", None)
        try:
            inner = sqlglot.parse_one(
                f"SELECT * FROM {original.sql(dialect='mysql')} WHERE {predicate}",
                read="mysql",
            )
        except Exception as exc:
            raise SqlPolicyError("租户过滤无法安全重写，已拒绝执行") from exc
        alias = table.alias or table.name
        table.replace(exp.Subquery(
            this=inner,
            alias=exp.TableAlias(this=exp.to_identifier(alias)),
        ))
    try:
        return tree.sql(dialect="mysql")
    except Exception as exc:
        raise SqlPolicyError("租户过滤重写失败，已拒绝执行") from exc
