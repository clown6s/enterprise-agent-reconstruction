"""基于 AST 的 SELECT 语句行级安全重写。"""
from __future__ import annotations

import re
import uuid

import sqlglot
from sqlglot import exp

from ...domain.exceptions import SqlPolicyError
from .row_policy import BoundPolicy

_MARKER = re.compile(r"__RLS_MARKER_[A-Za-z0-9]+_[0-9]+__")


def rewrite_with_row_policies(
    sql: str, policies_by_table: dict[str, tuple[BoundPolicy, ...]]
) -> tuple[str, tuple]:
    """把每个受管控的物理表包装为带过滤条件的派生表。

    ``BoundPolicy.sql`` 包含 DB-API 的 ``%s`` 占位符，sqlglot 无法将其解析为
    占位符。因此在 AST 构造期间使用唯一标识符标记，序列化后再替换回去；
    参数值始终保留在 params 中。
    """
    if not policies_by_table:
        return sql, ()
    try:
        tree = sqlglot.parse_one(sql, read="mysql")
    except Exception as exc:
        raise SqlPolicyError("行级权限 SQL 无法解析，已拒绝执行") from exc

    table_nodes = list(tree.find_all(exp.Table))
    if not table_nodes:
        raise SqlPolicyError("存在行级权限但 SQL 未找到物理表，已拒绝执行")

    normalized = {str(name).split(".")[-1].lower(): tuple(policies)
                  for name, policies in policies_by_table.items()}
    seen: set[str] = set()
    marker_values: dict[str, str] = {}
    params: list = []
    suffix = uuid.uuid4().hex

    for table in table_nodes:
        table_name = table.name.lower()
        policies = normalized.get(table_name)
        if not policies:
            continue
        seen.add(table_name)
        fragments: list[str] = []
        for policy_index, policy in enumerate(policies):
            if not isinstance(policy, BoundPolicy):
                raise SqlPolicyError("行级权限策略格式无效，已拒绝执行")
            marker_index = 0

            def replace_marker(_match):
                nonlocal marker_index
                marker = f"__RLS_MARKER_{suffix}_{len(params)}__"
                if marker in marker_values:
                    raise SqlPolicyError("行级权限占位符冲突，已拒绝执行")
                marker_values[marker] = "%s"
                if marker_index >= len(policy.params):
                    raise SqlPolicyError("行级权限参数数量不匹配，已拒绝执行")
                params.append(policy.params[marker_index])
                marker_index += 1
                return marker

            fragment = re.sub(r"%s", replace_marker, policy.sql)
            if marker_index != len(policy.params):
                raise SqlPolicyError("行级权限参数数量不匹配，已拒绝执行")
            fragments.append(f"({fragment})")
        predicate = " AND ".join(fragments)

        # 使用原始表标识符，但刻意省略其别名
        # （在派生表内部），使限定与未限定的策略
        # 都能引用物理表。
        inner_table = table.copy()
        inner_table.set("alias", None)
        try:
            inner = sqlglot.parse_one(
                f"SELECT * FROM {inner_table.sql(dialect='mysql')} WHERE {predicate}",
                read="mysql",
            )
        except Exception as exc:
            raise SqlPolicyError("行级权限谓词无法安全重写，已拒绝执行") from exc
        alias = table.alias or table.name
        subquery = exp.Subquery(
            this=inner,
            alias=exp.TableAlias(this=exp.to_identifier(alias)),
        )
        table.replace(subquery)

    missing = set(normalized) - seen
    if missing:
        raise SqlPolicyError("行级权限策略未匹配到物理表，已拒绝执行")
    try:
        rewritten = tree.sql(dialect="mysql")
    except Exception as exc:
        raise SqlPolicyError("行级权限 SQL 重写失败，已拒绝执行") from exc
    for marker, replacement in marker_values.items():
        rewritten = rewritten.replace(marker, replacement)
    if rewritten.count("%s") != len(params):
        raise SqlPolicyError("行级权限参数与 SQL 占位符不匹配，已拒绝执行")
    return rewritten, tuple(params)
