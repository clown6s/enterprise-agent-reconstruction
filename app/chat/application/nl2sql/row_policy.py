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
