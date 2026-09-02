"""MySQL implementation of the governed NL2SQL schema catalog."""
import json

from ..application.context import identity
from ..application.ports import SchemaCatalog
from ..domain.exceptions import ValidationError
from .mysql_pool import MysqlPool, mysql_errors


class MysqlSchemaCatalog(SchemaCatalog):
    def __init__(self, pool: MysqlPool):
        self._pool = pool

    def _denied_domain_ids(self, cur, tenant_id, user_id) -> set:
        """Basic domain-level deny filter (sql_domain_permissions).

        Only explicit user-level `allowed=0` rows are treated as denial; the
        absence of any row leaves the domain accessible (permissions are an
        optional, additive access-control layer on top of the SQL Guard).
        """
        cur.execute(
            "SELECT domain_id FROM sql_domain_permissions "
            "WHERE tenant_id=%s AND subject_type='user' "
            "AND subject_id=%s AND allowed=0",
            (tenant_id, user_id),
        )
        return {row["domain_id"] for row in cur.fetchall()}

    @mysql_errors
    def domains(self, *, context) -> list[str]:
        tenant_id, _ = identity(context)
        def operation(conn):
            with conn.cursor() as cur:
                denied = self._denied_domain_ids(cur, tenant_id, context.user_id)
                cur.execute(
                    "SELECT domain_id, domain_name FROM sql_data_domains "
                    "WHERE tenant_id=%s AND status='active' ORDER BY domain_name",
                    (tenant_id,),
                )
                return [row["domain_name"] for row in cur.fetchall()
                        if row["domain_id"] not in denied]
        return self._pool.run(operation)

    @mysql_errors
    def describe(self, domain: str, *, context) -> str:
        tenant_id, user_id = identity(context)
        def operation(conn):
            with conn.cursor() as cur:
                denied = self._denied_domain_ids(cur, tenant_id, user_id)
                cur.execute(
                    "SELECT domain_id, description FROM sql_data_domains "
                    "WHERE tenant_id=%s AND domain_name=%s AND status='active' LIMIT 1",
                    (tenant_id, domain),
                )
                item = cur.fetchone()
                if item is None or item["domain_id"] in denied:
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
                cur.execute(
                    "SELECT table_name, allowed_joins FROM sql_allowed_tables "
                    "WHERE tenant_id=%s AND domain_id=%s ORDER BY table_name",
                    (tenant_id, item["domain_id"]),
                )
                joins = {r["table_name"]: r["allowed_joins"] for r in cur.fetchall()}
            lines = [f"数据域: {domain}\n{item['description']}"]
            current = None
            for row in rows:
                if row["table_name"] != current:
                    current = row["table_name"]
                    lines.append(f"表 {current}: {row.get('table_description') or ''}")
                    for join_line in self._format_joins(joins.get(current), current):
                        lines.append(join_line)
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

    @staticmethod
    def _format_joins(raw, table: str) -> list[str]:
        """Render a table's `allowed_joins` JSON as governed-JOIN hint lines.

        Accepts a JSON array of join specs or a dict keyed by target table. A
        single spec may be:

        * ``{"table": "customers", "columns": {"customer_id": "id"}, "join_type": "LEFT"}``
          (the Registry's canonical format; ``table`` names the target),
        * ``{"target": "order_items", "condition": "orders.id=...", "type": "LEFT"}``,
        * a dict ``{"order_items": "orders.id=order_items.order_id"}``.
        """
        if raw is None:
            return []
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8", "replace")
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except (ValueError, TypeError):
                return []
        if not isinstance(raw, (list, dict)):
            return []
        items = raw if isinstance(raw, list) else raw.items()
        out = []
        for entry in items:
            if isinstance(raw, dict):
                target, spec = entry
            else:
                spec = entry
                target = spec.get("target") if isinstance(spec, dict) else None
            if not isinstance(spec, dict):
                continue
            join_type = (spec.get("type") or spec.get("join_type") or "LEFT").upper()
            # Registry format: {"table": target, "columns": {left_col: right_col}}
            registry_target = spec.get("table")
            columns = spec.get("columns")
            if registry_target and isinstance(columns, dict) and columns:
                target = registry_target
                parts = [f"{table}.{left}={registry_target}.{right}"
                         for left, right in columns.items()]
                condition = " AND ".join(parts)
                out.append(f"  关联: {join_type} JOIN {target} ON {condition}")
                continue
            condition = spec.get("condition") or spec.get("on") or spec.get("on_clause")
            if target is None or not condition:
                continue
            out.append(f"  关联: {join_type} JOIN {target} ON {condition}")
        return out

    @mysql_errors
    def allowed_tables(self, domain: str, *, context) -> set[str]:
        tenant_id, _ = identity(context)
        def operation(conn):
            with conn.cursor() as cur:
                denied = self._denied_domain_ids(cur, tenant_id, context.user_id)
                cur.execute(
                    "SELECT t.table_name, t.domain_id FROM sql_allowed_tables t "
                    "JOIN sql_data_domains d ON d.tenant_id=t.tenant_id "
                    "AND d.domain_id=t.domain_id WHERE t.tenant_id=%s "
                    "AND d.domain_name=%s AND d.status='active'",
                    (tenant_id, domain),
                )
                return {row["table_name"] for row in cur.fetchall()
                        if row["domain_id"] not in denied}
        return self._pool.run(operation)

    @mysql_errors
    def blocked_columns(self, domain: str, *, context) -> dict[str, set[str]]:
        """Sensitive columns that must not appear in generated SQL, per table."""
        tenant_id, _ = identity(context)
        def operation(conn):
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT domain_id FROM sql_data_domains "
                    "WHERE tenant_id=%s AND domain_name=%s AND status='active' LIMIT 1",
                    (tenant_id, domain),
                )
                item = cur.fetchone()
                if item is None:
                    return {}
                cur.execute(
                    "SELECT table_name, column_name FROM sql_allowed_columns "
                    "WHERE tenant_id=%s AND domain_id=%s AND `sensitive`=1 "
                    "ORDER BY table_name, column_name",
                    (tenant_id, item["domain_id"]),
                )
                blocked: dict[str, set[str]] = {}
                for row in cur.fetchall():
                    blocked.setdefault(row["table_name"], set()).add(row["column_name"])
                return blocked
        return self._pool.run(operation)

    @mysql_errors
    def row_policies(self, domain: str, table_name: str, *, context) -> tuple:
        """Resolve table policies for the caller; any matching deny wins."""
        tenant_id, user_id = identity(context)
        roles = tuple(getattr(context, "roles", ()) or ())
        departments = tuple(getattr(context, "department_ids", ()) or ())

        def operation(conn):
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT domain_id FROM sql_data_domains "
                    "WHERE tenant_id=%s AND domain_name=%s AND status='active' LIMIT 1",
                    (tenant_id, domain),
                )
                item = cur.fetchone()
                if item is None:
                    return ()
                branches = ["(subject_type='user' AND subject_id=%s)"]
                params = [tenant_id, item["domain_id"], table_name, user_id]
                if roles:
                    marks = ", ".join(["%s"] * len(roles))
                    branches.append(
                        f"(subject_type='role' AND subject_id IN ({marks}))")
                    params.extend(roles)
                if departments:
                    marks = ", ".join(["%s"] * len(departments))
                    branches.append(
                        f"(subject_type='department' AND subject_id IN ({marks}))")
                    params.extend(departments)
                cur.execute(
                    "SELECT subject_type, subject_id, row_predicate_template, allowed "
                    "FROM sql_domain_permissions "
                    "WHERE tenant_id=%s AND domain_id=%s AND table_name=%s "
                    "AND (" + " OR ".join(branches) + ")",
                    tuple(params),
                )
                rows = cur.fetchall()
            if not rows:
                return ()
            from ..application.nl2sql.row_policy import bind_policy
            if any(not bool(row.get("allowed")) for row in rows):
                raise ValidationError("行级权限拒绝访问该表")
            return tuple(
                bind_policy(row["row_predicate_template"], tenant_id=tenant_id,
                            user_id=user_id, role_names=roles,
                            department_ids=departments)
                for row in rows if bool(row.get("allowed")))

        return self._pool.run(operation)

    @mysql_errors
    def resolve_domain(self, query: str, *, context) -> str | None:
        tenant_id, _ = identity(context)
        def operation(conn):
            with conn.cursor() as cur:
                denied = self._denied_domain_ids(cur, tenant_id, context.user_id)
                cur.execute(
                    "SELECT d.domain_name, d.domain_id, k.keyword, k.weight "
                    "FROM sql_domain_keywords k "
                    "JOIN sql_data_domains d "
                    "ON d.tenant_id=k.tenant_id AND d.domain_id=k.domain_id "
                    "WHERE k.tenant_id=%s AND d.status='active'",
                    (tenant_id,),
                )
                rows = [r for r in cur.fetchall() if r["domain_id"] not in denied]
            if rows:
                scores = {}  # domain_name -> 累计权重
                for row in rows:
                    keyword = row["keyword"]
                    if keyword and keyword in query:
                        bonus = 1.0 + min(len(keyword), 8) * 0.1
                        scores[row["domain_name"]] = scores.get(
                            row["domain_name"], 0.0) + float(row["weight"]) * bonus
                if scores:
                    ordered = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
                    top, top_score = ordered[0]
                    if len(ordered) == 1 or ordered[1][1] * 1.3 < top_score:
                        return top
                    return None  # 多个域都命中且分差小，需要澄清
            # 回退：domain_name 直接包含整句（英文别名场景）
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT domain_id, domain_name FROM sql_data_domains "
                    "WHERE tenant_id=%s AND status='active' "
                    "AND domain_name LIKE %s "
                    "ORDER BY CHAR_LENGTH(domain_name) DESC LIMIT 1",
                    (tenant_id, f"%{query}%"),
                )
                row = cur.fetchone()
            if row is None or row["domain_id"] in denied:
                return None
            return row["domain_name"]
        return self._pool.run(operation)

    def close(self) -> None:
        self._pool.close()
