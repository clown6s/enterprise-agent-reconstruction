"""Restricted row-level policy templates and DB-API parameter binding.

Templates are predicate fragments using only trusted context placeholders:
``:tenant_id``, ``:user_id``, ``:role_names`` and ``:department_ids``.
Values are always returned separately as DB-API parameters; never interpolate
identity values into SQL text.
"""
from dataclasses import dataclass
import re

from ...domain.exceptions import SqlPolicyError

_MAX_TEMPLATE_LENGTH = 2000
_SCALARS = frozenset({"tenant_id", "user_id"})
_LISTS = frozenset({"role_names", "department_ids"})
_ALLOWED = _SCALARS | _LISTS
_TOKEN = re.compile(r"(?<!:):[A-Za-z_][A-Za-z0-9_]*")
_BLOCKED = ("insert", "update", "delete", "drop", "alter", "truncate",
            "create", "grant", "revoke", "call", "exec", "merge",
            "replace", "select", "union", "into")
_FORBIDDEN = (re.compile(r";"), re.compile(r"--"), re.compile(r"/\*"),
              re.compile(r"\*/"))
_POLICY_PLACEHOLDERS = frozenset({"tenant_id", "user_id", "role_names", "department_ids"})
_POLICY_KEYWORDS = frozenset({
    "and", "or", "not", "in", "is", "null", "between", "like", "regexp",
    "true", "false", "div", "mod", "binary", "cast", "as", "signed", "unsigned",
    "decimal", "char", "date", "datetime", "time", "json", "bool", "boolean",
})
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*")


@dataclass(frozen=True)
class BoundPolicy:
    """Predicate SQL containing ``%s`` markers and ordered parameter values."""
    sql: str
    params: tuple = ()


def compile_template(template: str) -> str:
    """Validate a policy predicate template, raising on unsafe syntax."""
    if not isinstance(template, str) or not template.strip():
        raise SqlPolicyError("行级权限模板为空")
    template = template.strip()
    if len(template) > _MAX_TEMPLATE_LENGTH:
        raise SqlPolicyError("行级权限模板过长")
    if "%" in template:
        raise SqlPolicyError("行级权限模板禁止包含 %")
    lower = template.lower()
    for keyword in _BLOCKED:
        if re.search(rf"\b{keyword}\b", lower):
            raise SqlPolicyError(f"行级权限模板包含禁止关键字: {keyword}")
    for pattern in _FORBIDDEN:
        if pattern.search(template):
            raise SqlPolicyError("行级权限模板包含被禁止的符号")
    for token in _TOKEN.findall(template):
        if token[1:] not in _ALLOWED:
            raise SqlPolicyError(f"行级权限模板包含未授权占位符: {token}")
    return template


def _extract_policy_columns(template: str) -> set[str]:
    """提取策略谓词中引用的裸列名。

    占位符（``:tenant_id`` 等）、SQL 关键字、字符串字面量和 ``::`` 类型
    转换标记都会被排除，避免把非真实列当成列名。
    """
    stripped = re.sub(r"'[^']*'|\"[^\"]*\"", " ", template)
    stripped = re.sub(r"`([^`]*)`", r"\1", stripped)
    stripped = re.sub(r"::\s*[A-Za-z_][A-Za-z0-9_]*", " ", stripped)
    return {
        token.lower()
        for token in _IDENTIFIER.findall(stripped)
        if token.lower() not in _POLICY_PLACEHOLDERS
        and token.lower() not in _POLICY_KEYWORDS
    }


def validate_policy_columns(template: str, columns: dict[str, bool],
                            *, sensitive: set[str] = frozenset()) -> set[str]:
    """校验策略引用的列属于已登记的明文可过滤列。

    ``columns`` 为列名到是否可过滤的映射；``sensitive`` 为敏感列集合。
    返回通过校验的列名集合；任一引用列不合法时抛出 ValidationError。
    """
    from ...domain.exceptions import ValidationError
    referenced = _extract_policy_columns(template)
    unknown = referenced - set(columns)
    if unknown:
        raise ValidationError(
            "策略引用了未登记或未授权的字段: " + ", ".join(sorted(unknown)))
    blocked = {
        name for name in referenced
        if name in sensitive or not columns.get(name.lower(), False)
    }
    if blocked:
        raise ValidationError(
            "策略引用了敏感或不可过滤的字段: " + ", ".join(sorted(blocked)))
    return referenced


def bind_policy(template: str, *, tenant_id: str | None = None,
                user_id: str | None = None, role_names=(),
                department_ids=()) -> BoundPolicy:
    """Compile and bind a policy against trusted identity attributes.

    List placeholders expand to a parenthesized marker list. Empty lists use
    ``(NULL)`` so an ``IN :list`` predicate safely matches no rows.
    """
    template = compile_template(template)
    values = {"tenant_id": tenant_id, "user_id": user_id,
              "role_names": tuple(role_names or ()),
              "department_ids": tuple(department_ids or ())}
    output: list[str] = []
    params: list = []
    offset = 0
    for match in _TOKEN.finditer(template):
        output.append(template[offset:match.start()])
        name = match.group(0)[1:]
        value = values[name]
        if name in _SCALARS:
            if value is None or value == "":
                raise SqlPolicyError(f"行级权限模板缺少上下文值: {name}")
            output.append("%s")
            params.append(value)
        else:
            if value:
                output.append("(" + ", ".join(["%s"] * len(value)) + ")")
                params.extend(value)
            else:
                output.append("(NULL)")
        offset = match.end()
    output.append(template[offset:])
    return BoundPolicy("".join(output), tuple(params))
