"""Schema Registry MVP DTOs and application service.

The service contains no persistence or framework code; MySQL concerns live in
``MysqlSchemaRegistry``.  A registry has one mutable definition per domain and
publishing changes its status to active after validation.
"""
from dataclasses import dataclass, field
import re
from typing import Any

from ..domain.exceptions import ValidationError

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")


def validate_identifier(value: str, label: str = "标识符") -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise ValidationError(f"{label}无效")
    return value


@dataclass(frozen=True)
class SchemaColumn:
    column_name: str
    data_type: str
    business_name: str = ""
    description: str | None = None
    selectable: bool = True
    filterable: bool = True
    sortable: bool = False
    aggregatable: bool = False
    sensitive: bool = False
    masking_rule: str | None = None


@dataclass(frozen=True)
class SchemaJoin:
    table: str
    columns: dict[str, str]
    join_type: str = "INNER"


@dataclass(frozen=True)
class SchemaTable:
    table_name: str
    description: str | None = None
    required_tenant_filter: bool = True
    columns: tuple[SchemaColumn, ...] = ()
    allowed_joins: tuple[SchemaJoin, ...] = ()


@dataclass(frozen=True)
class RowPolicyRegistration:
    table_name: str
    subject_type: str
    subject_id: str
    predicate_template: str
    allowed: bool = True


@dataclass(frozen=True)
class SchemaDomain:
    domain_id: str
    domain_name: str
    description: str
    tables: tuple[SchemaTable, ...] = ()
    default_time_column: str | None = None
    max_rows: int = 1000
    max_execution_seconds: int = 10
    keywords: tuple[str, ...] = ()


class SchemaRegistry:
    """Pure validation/orchestration service over a SchemaRegistryPort."""
    def __init__(self, port):
        self._port = port

    def introspect(self, *, context, tables: list[str] | tuple[str, ...] | None = None,
                   include_columns: bool = True):
        return self._port.introspect(context=context, tables=tables,
                                     include_columns=include_columns)

    def list_domains(self, *, context):
        return self._port.list_domains(context=context)

    def list_tables(self, domain_id: str, *, context):
        validate_identifier(domain_id, "数据域ID")
        return self._port.list_tables(domain_id, context=context)

    def list_columns(self, domain_id: str, table_name: str, *, context):
        validate_identifier(domain_id, "数据域ID")
        validate_identifier(table_name, "表名")
        return self._port.list_columns(domain_id, table_name, context=context)

    def list_joins(self, domain_id: str, *, context):
        validate_identifier(domain_id, "数据域ID")
        return self._port.list_joins(domain_id, context=context)

    def register_domain(self, domain: SchemaDomain, *, context) -> None:
        self._validate_domain(domain)
        return self._port.register_domain(domain, context=context)

    def register_table(self, domain_id: str, table: SchemaTable, *, context) -> None:
        validate_identifier(domain_id, "数据域ID")
        self._validate_table(table)
        return self._port.register_table(domain_id, table, context=context)

    def register_columns(self, domain_id: str, table_name: str,
                         columns: list[SchemaColumn] | tuple[SchemaColumn, ...], *, context) -> None:
        validate_identifier(domain_id, "数据域ID"); validate_identifier(table_name, "表名")
        for c in columns: self._validate_column(c)
        return self._port.register_columns(domain_id, table_name, columns, context=context)

    def register_joins(self, domain_id: str, table_name: str,
                       joins: list[SchemaJoin] | tuple[SchemaJoin, ...], *, context) -> None:
        validate_identifier(domain_id, "数据域ID"); validate_identifier(table_name, "表名")
        for j in joins: self._validate_join(j)
        return self._port.register_joins(domain_id, table_name, joins, context=context)

    def register_row_policy(self, domain_id: str, policy: RowPolicyRegistration,
                            *, context) -> None:
        validate_identifier(domain_id, "数据域ID")
        validate_identifier(policy.table_name, "表名")
        if policy.subject_type not in ("user", "role", "department"):
            raise ValidationError("subject_type 只允许 user/role/department")
        if not policy.subject_id or len(policy.subject_id) > 64:
            raise ValidationError("subject_id 无效")
        from .nl2sql.row_policy import compile_template
        compile_template(policy.predicate_template)
        return self._port.register_row_policy(domain_id, policy, context=context)

    def list_row_policies(self, domain_id: str, *, context) -> list[dict]:
        validate_identifier(domain_id, "数据域ID")
        return self._port.list_row_policies(domain_id, context=context)

    def delete_row_policy(self, domain_id: str, permission_id: int, *, context) -> None:
        validate_identifier(domain_id, "数据域ID")
        return self._port.delete_row_policy(domain_id, permission_id, context=context)

    def publish(self, domain_id: str, *, context, version: int | None = None,
                reason: str | None = None) -> dict | None:
        validate_identifier(domain_id, "数据域ID")
        if version is not None and (isinstance(version, bool) or
                                    not isinstance(version, int) or version <= 0):
            raise ValidationError("版本必须是正整数")
        if reason is not None and len(reason) > 500:
            raise ValidationError("发布原因过长")
        return self._port.publish(domain_id, context=context, version=version,
                                  reason=reason)

    @classmethod
    def _validate_domain(cls, d):
        validate_identifier(d.domain_id, "数据域ID")
        if not d.domain_name or len(d.domain_name) > 128: raise ValidationError("数据域名称无效")
        if d.max_rows <= 0 or d.max_execution_seconds <= 0: raise ValidationError("数据域限制无效")
        for t in d.tables: cls._validate_table(t)

    @classmethod
    def _validate_table(cls, t):
        validate_identifier(t.table_name, "表名")
        for c in t.columns: cls._validate_column(c)
        for j in t.allowed_joins: cls._validate_join(j)

    @staticmethod
    def _validate_column(c): validate_identifier(c.column_name, "列名")
    @staticmethod
    def _validate_join(j):
        validate_identifier(j.table, "JOIN表名")
        if j.join_type.upper() not in {"INNER", "LEFT", "RIGHT"}: raise ValidationError("JOIN类型无效")
        if not j.columns or any(not isinstance(k, str) or not isinstance(v, str) or not _IDENTIFIER.fullmatch(k) or not _IDENTIFIER.fullmatch(v) for k,v in j.columns.items()): raise ValidationError("JOIN列映射无效")

# 供 API 调用者使用的友好 DTO 别名。
ColumnDTO = SchemaColumn
JoinDTO = SchemaJoin
TableDTO = SchemaTable
DomainDTO = SchemaDomain
