"""MySQL implementation of the governed NL2SQL schema catalog."""
from ..application.context import identity
from ..application.ports import SchemaCatalog
from .mysql_pool import MysqlPool, mysql_errors


class MysqlSchemaCatalog(SchemaCatalog):
    def __init__(self, pool: MysqlPool):
        self._pool = pool

    @mysql_errors
    def domains(self, *, context) -> list[str]:
        tenant_id, _ = identity(context)
        def operation(conn):
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT domain_name FROM sql_data_domains "
                    "WHERE tenant_id=%s AND status='active' ORDER BY domain_name",
                    (tenant_id,),
                )
                return [row["domain_name"] for row in cur.fetchall()]
        return self._pool.run(operation)

    @mysql_errors
    def describe(self, domain: str, *, context) -> str:
        tenant_id, _ = identity(context)
        def operation(conn):
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT domain_id, description FROM sql_data_domains "
                    "WHERE tenant_id=%s AND domain_name=%s AND status='active' LIMIT 1",
                    (tenant_id, domain),
                )
                item = cur.fetchone()
                if item is None:
                    return ""
                cur.execute(
                    "SELECT t.table_name, t.table_description, c.column_name, "
                    "c.business_name, c.data_type, c.selectable, c.filterable, "
                    "c.sortable, c.aggregatable FROM sql_allowed_tables t "
                    "LEFT JOIN sql_allowed_columns c ON c.tenant_id=t.tenant_id "
                    "AND c.domain_id=t.domain_id AND c.table_name=t.table_name "
                    "WHERE t.tenant_id=%s AND t.domain_id=%s ORDER BY t.table_name, c.column_name",
                    (tenant_id, item["domain_id"]),
                )
                rows = cur.fetchall()
            lines = [f"数据域: {domain}\n{item['description']}"]
            current = None
            for row in rows:
                if row["table_name"] != current:
                    current = row["table_name"]
                    lines.append(f"表 {current}: {row.get('table_description') or ''}")
                if row.get("column_name"):
                    flags = []
                    for key, label in (("selectable", "select"), ("filterable", "filter"),
                                       ("sortable", "sort"), ("aggregatable", "aggregate")):
                        if row.get(key):
                            flags.append(label)
                    lines.append(f"  {row['column_name']} ({row['data_type']}) "
                                 f"{row['business_name']} [{','.join(flags)}]")
            return "\n".join(lines)
        return self._pool.run(operation)

    @mysql_errors
    def allowed_tables(self, domain: str, *, context) -> set[str]:
        tenant_id, _ = identity(context)
        def operation(conn):
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT t.table_name FROM sql_allowed_tables t "
                    "JOIN sql_data_domains d ON d.tenant_id=t.tenant_id "
                    "AND d.domain_id=t.domain_id WHERE t.tenant_id=%s "
                    "AND d.domain_name=%s AND d.status='active'",
                    (tenant_id, domain),
                )
                return {row["table_name"] for row in cur.fetchall()}
        return self._pool.run(operation)

    @mysql_errors
    def resolve_domain(self, query: str, *, context) -> str | None:
        tenant_id, _ = identity(context)
        def operation(conn):
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT domain_name FROM sql_data_domains "
                    "WHERE tenant_id=%s AND status='active' "
                    "AND (domain_name LIKE %s OR description LIKE %s) "
                    "ORDER BY CHAR_LENGTH(domain_name) DESC LIMIT 1",
                    (tenant_id, f"%{query}%", f"%{query}%"),
                )
                row = cur.fetchone()
            return row["domain_name"] if row else None
        return self._pool.run(operation)

    def close(self) -> None:
        self._pool.close()
