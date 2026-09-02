"""MySQL persistence adapter for the Schema Registry MVP."""
import json
from ..application.context import identity
from ..application.ports import SchemaRegistryPort
from ..application.schema_registry import validate_identifier
from ..domain.exceptions import ValidationError
from .mysql_pool import MysqlPool, mysql_errors


class MysqlSchemaRegistry(SchemaRegistryPort):
    def __init__(self, pool: MysqlPool):
        self._pool = pool

    @staticmethod
    def _admin(context):
        tenant, user = identity(context)
        if not getattr(context, "can", lambda _: False)("schema:admin"):
            raise ValidationError("缺少schema:admin权限")
        return tenant, user

    @mysql_errors
    def introspect(self, *, context, tables=None, include_columns=True):
        tenant, _ = self._admin(context)
        names = None if tables is None else [validate_identifier(x, "表名") for x in tables]
        def op(conn):
            with conn.cursor() as cur:
                sql = ("SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE, ORDINAL_POSITION "
                       "FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE()")
                params = []
                if names:
                    sql += " AND TABLE_NAME IN (" + ",".join(["%s"] * len(names)) + ")"; params.extend(names)
                sql += " ORDER BY TABLE_NAME, ORDINAL_POSITION"
                cur.execute(sql, params)
                rows = cur.fetchall()
            result = {}
            for r in rows:
                result.setdefault(r["TABLE_NAME"], []).append({"column_name": r["COLUMN_NAME"], "data_type": r["DATA_TYPE"]})
            if include_columns:
                return [{"table_name": n, "columns": c} for n, c in result.items()]
            return [{"table_name": n, "columns": []} for n in result]
        return self._pool.run(op)

    @mysql_errors
    def register_domain(self, domain, *, context):
        tenant, user = self._admin(context)
        def op(conn):
            with conn.cursor() as c:
                c.execute("INSERT INTO sql_data_domains (tenant_id,domain_id,domain_name,description,default_time_column,max_rows,max_execution_seconds,created_by,updated_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE domain_name=VALUES(domain_name),description=VALUES(description),default_time_column=VALUES(default_time_column),max_rows=VALUES(max_rows),max_execution_seconds=VALUES(max_execution_seconds),updated_by=VALUES(updated_by)", (tenant,domain.domain_id,domain.domain_name,domain.description,domain.default_time_column,domain.max_rows,domain.max_execution_seconds,user,user))
                if domain.keywords:
                    c.executemany("INSERT INTO sql_domain_keywords (tenant_id,domain_id,keyword,weight) VALUES (%s,%s,%s,1) ON DUPLICATE KEY UPDATE weight=VALUES(weight)", [(tenant,domain.domain_id,k) for k in domain.keywords])
            conn.commit()
        return self._pool.run(op)

    @mysql_errors
    def register_table(self, domain_id, table, *, context):
        validate_identifier(domain_id, "数据域ID")
        validate_identifier(table.table_name, "表名")
        tenant, _ = self._admin(context)
        def op(conn):
            with conn.cursor() as c:
                c.execute("INSERT INTO sql_allowed_tables (tenant_id,domain_id,table_name,table_description,required_tenant_filter,allowed_joins) VALUES (%s,%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE table_description=VALUES(table_description),required_tenant_filter=VALUES(required_tenant_filter)", (tenant,domain_id,table.table_name,table.description,table.required_tenant_filter,json.dumps([])))
            conn.commit()
        return self._pool.run(op)

    @mysql_errors
    def register_columns(self, domain_id, table_name, columns, *, context):
        validate_identifier(domain_id, "数据域ID"); validate_identifier(table_name, "表名")
        tenant, _ = self._admin(context)
        def op(conn):
            with conn.cursor() as c:
                for x in columns:
                    c.execute("INSERT INTO sql_allowed_columns (tenant_id,domain_id,table_name,column_name,business_name,data_type,selectable,filterable,sortable,aggregatable,`sensitive`,masking_rule,description) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE business_name=VALUES(business_name),data_type=VALUES(data_type),selectable=VALUES(selectable),filterable=VALUES(filterable),sortable=VALUES(sortable),aggregatable=VALUES(aggregatable),`sensitive`=VALUES(`sensitive`),masking_rule=VALUES(masking_rule),description=VALUES(description)", (tenant,domain_id,table_name,x.column_name,x.business_name,x.data_type,x.selectable,x.filterable,x.sortable,x.aggregatable,x.sensitive,x.masking_rule,x.description))
            conn.commit()
        return self._pool.run(op)

    @mysql_errors
    def register_joins(self, domain_id, table_name, joins, *, context):
        validate_identifier(domain_id, "数据域ID"); validate_identifier(table_name, "表名")
        tenant, _ = self._admin(context)
        payload = [{"table": j.table, "columns": j.columns, "join_type": j.join_type.upper()} for j in joins]
        def op(conn):
            with conn.cursor() as c: c.execute("UPDATE sql_allowed_tables SET allowed_joins=%s WHERE tenant_id=%s AND domain_id=%s AND table_name=%s", (json.dumps(payload),tenant,domain_id,table_name))
            conn.commit()
        return self._pool.run(op)

    @mysql_errors
    def publish(self, domain_id, *, context, version=None, reason=None):
        tenant, user = self._admin(context)
        def op(conn):
            with conn.cursor() as c:
                c.execute("SELECT domain_name, description, default_time_column, max_rows, max_execution_seconds FROM sql_data_domains WHERE tenant_id=%s AND domain_id=%s FOR UPDATE", (tenant, domain_id))
                domain = c.fetchone()
                if not domain:
                    raise ValidationError("数据域不存在")
                c.execute("SELECT table_name, table_description, required_tenant_filter, allowed_joins FROM sql_allowed_tables WHERE tenant_id=%s AND domain_id=%s ORDER BY table_name", (tenant, domain_id))
                tables = c.fetchall()
                if not tables:
                    raise ValidationError("数据域至少需要一张表")
                snapshot = {"domain": dict(domain), "tables": []}
                for table in tables:
                    c.execute("SELECT column_name, business_name, data_type, selectable, filterable, sortable, aggregatable, `sensitive`, masking_rule, description FROM sql_allowed_columns WHERE tenant_id=%s AND domain_id=%s AND table_name=%s ORDER BY column_name", (tenant, domain_id, table["table_name"]))
                    snapshot["tables"].append({"table": dict(table), "columns": c.fetchall()})
                canonical = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
                import hashlib
                from uuid import uuid4
                snapshot_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
                if version is None:
                    c.execute("SELECT COALESCE(MAX(version_no), 0) AS n FROM sql_schema_versions WHERE tenant_id=%s AND domain_id=%s FOR UPDATE", (tenant, domain_id))
                    version_no = int(c.fetchone()["n"]) + 1
                else:
                    try:
                        version_no = int(version)
                    except (TypeError, ValueError) as exc:
                        raise ValidationError("版本必须是正整数") from exc
                    if version_no <= 0:
                        raise ValidationError("版本必须是正整数")
                version_id = str(uuid4())
                c.execute("UPDATE sql_schema_versions SET status='superseded' WHERE tenant_id=%s AND domain_id=%s AND status='published'", (tenant, domain_id))
                c.execute("INSERT INTO sql_schema_versions (tenant_id,version_id,domain_id,version_no,status,snapshot_hash,created_by,published_by,change_reason,published_at) VALUES (%s,%s,%s,%s,'published',%s,%s,%s,%s,NOW(6))", (tenant, version_id, domain_id, version_no, snapshot_hash, user, user, reason))
                for item in snapshot["tables"]:
                    raw = item["table"].get("allowed_joins")
                    if isinstance(raw, str):
                        try: raw = json.loads(raw)
                        except (TypeError, ValueError): raw = []
                    for join in (raw if isinstance(raw, list) else []):
                        if not isinstance(join, dict):
                            continue
                        target = join.get("table") or join.get("target")
                        columns = join.get("columns") or {}
                        if target and isinstance(columns, dict):
                            for left, right in columns.items():
                                c.execute("INSERT INTO sql_allowed_joins (tenant_id,join_id,version_id,left_domain_id,left_table_name,left_column_name,right_domain_id,right_table_name,right_column_name,join_type,description) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", (tenant, str(uuid4()), version_id, domain_id, item["table"]["table_name"], left, domain_id, target, right, (join.get("join_type") or "left").lower(), join.get("description")))
                c.execute("UPDATE sql_data_domains SET status='active',updated_by=%s WHERE tenant_id=%s AND domain_id=%s", (user, tenant, domain_id))
                c.execute("INSERT INTO sql_schema_change_logs (tenant_id,change_id,version_id,domain_id,action,changed_by,change_summary) VALUES (%s,%s,%s,%s,'publish',%s,%s)", (tenant, str(uuid4()), version_id, domain_id, user, json.dumps({"version_no": version_no, "snapshot_hash": snapshot_hash, "reason": reason or ""}, ensure_ascii=False)))
            conn.commit()
            return {"version_id": version_id, "version_no": version_no, "snapshot_hash": snapshot_hash}
        return self._pool.run(op)

    @mysql_errors
    def list_domains(self, *, context):
        tenant, _ = self._admin(context)
        def op(conn):
            with conn.cursor() as c:
                c.execute("SELECT domain_id, domain_name, description, status, updated_at FROM sql_data_domains WHERE tenant_id=%s ORDER BY domain_name", (tenant,))
                return c.fetchall()
        return self._pool.run(op)

    @mysql_errors
    def list_tables(self, domain_id, *, context):
        tenant, _ = self._admin(context)
        def op(conn):
            with conn.cursor() as c:
                c.execute("SELECT table_name, table_description, required_tenant_filter, allowed_joins FROM sql_allowed_tables WHERE tenant_id=%s AND domain_id=%s ORDER BY table_name", (tenant, domain_id))
                return c.fetchall()
        return self._pool.run(op)

    @mysql_errors
    def list_columns(self, domain_id, table_name, *, context):
        tenant, _ = self._admin(context)
        def op(conn):
            with conn.cursor() as c:
                c.execute("SELECT column_name, business_name, data_type, selectable, filterable, sortable, aggregatable, sensitive, masking_rule, description FROM sql_allowed_columns WHERE tenant_id=%s AND domain_id=%s AND table_name=%s ORDER BY column_name", (tenant, domain_id, table_name))
                return c.fetchall()
        return self._pool.run(op)

    @mysql_errors
    def list_joins(self, domain_id, *, context):
        tenant, _ = self._admin(context)
        def op(conn):
            with conn.cursor() as c:
                c.execute("SELECT table_name, allowed_joins FROM sql_allowed_tables WHERE tenant_id=%s AND domain_id=%s ORDER BY table_name", (tenant, domain_id))
                result = []
                for row in c.fetchall():
                    value = row.get("allowed_joins")
                    if isinstance(value, (bytes, str)):
                        try: value = json.loads(value)
                        except (TypeError, ValueError): value = []
                    for join in (value if isinstance(value, list) else []):
                        if isinstance(join, dict): result.append({"source_table": row["table_name"], **join})
                return result
        return self._pool.run(op)

    def close(self): self._pool.close()
