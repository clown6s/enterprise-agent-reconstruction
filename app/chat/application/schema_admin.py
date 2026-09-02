"""Application facade for the schema administration HTTP adapter."""
import re
from uuid import uuid4

from .context import identity
from .schema_registry import SchemaColumn, SchemaDomain, SchemaJoin, SchemaTable


class SchemaAdminService:
    """Adapt admin API operations to the registry port without HTTP concerns."""
    def __init__(self, registry):
        self._registry = registry

    @staticmethod
    def _context(context):
        identity(context)
        if not context.can("schema:admin"):
            from ..domain.exceptions import ValidationError
            raise ValidationError("缺少schema:admin权限")
        return context

    def list_domains(self, *, context):
        return self._registry.list_domains(context=self._context(context))

    def create_domain(self, request, *, context):
        context = self._context(context)
        name = getattr(request, "name")
        domain_id = re.sub(r"[^A-Za-z0-9_]+", "_", name).strip("_").lower()[:64]
        if not domain_id:
            domain_id = "domain_" + uuid4().hex[:16]
        domain = SchemaDomain(domain_id=domain_id, domain_name=name,
                              description=getattr(request, "description", ""),
                              keywords=tuple(getattr(request, "keywords", ()) or ()))
        self._registry.register_domain(domain, context=context)
        return {"domain_id": domain_id, "domain_name": name, "status": "draft"}

    def list_tables(self, domain, *, context):
        return self._registry.list_tables(domain, context=self._context(context))

    def register_table(self, domain, request, *, context):
        context = self._context(context)
        table = SchemaTable(
            table_name=getattr(request, "table"),
            description=getattr(request, "description", ""),
            required_tenant_filter=getattr(request, "required_tenant_filter", True),
        )
        self._registry.register_table(domain, table, context=context)
        return {"domain_id": domain, "table": table.table_name, "status": "draft"}

    def introspect(self, domain, request=None, *, context):
        from .schema_registry import validate_identifier
        validate_identifier(domain, "数据域ID")
        tables = getattr(request, "tables", None) if request else None
        include_columns = getattr(request, "include_columns", True) if request else True
        return self._registry.introspect(
            context=self._context(context), tables=tables or None,
            include_columns=include_columns)

    def list_columns(self, domain, table, *, context):
        return self._registry.list_columns(domain, table, context=self._context(context))

    def list_joins(self, domain, *, context):
        return self._registry.list_joins(domain, context=self._context(context))

    def register_columns(self, domain, request, *, context):
        context = self._context(context)
        table = getattr(request, "table")
        columns = []
        for item in getattr(request, "columns", ()):
            columns.append(SchemaColumn(**item))
        self._registry.register_columns(domain, table, columns, context=context)
        return {"domain_id": domain, "table": table, "count": len(columns)}

    def register_joins(self, domain, request, *, context):
        context = self._context(context)
        table = getattr(request, "table")
        joins = [SchemaJoin(**item) for item in getattr(request, "joins", ())]
        self._registry.register_joins(domain, table, joins, context=context)
        return {"domain_id": domain, "table": table, "count": len(joins)}

    def publish(self, domain, request=None, *, context):
        version = getattr(request, "version", None) if request else None
        reason = getattr(request, "comment", None) if request else None
        result = self._registry.publish(domain, context=self._context(context),
                                        version=version, reason=reason or None)
        return {"domain_id": domain, "status": "active",
                **({} if result is None else result)}

    def close(self):
        closer = getattr(self._registry, "close", None)
        if callable(closer):
            closer()
