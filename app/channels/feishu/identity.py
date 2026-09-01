"""飞书 open_id 到本地 Principal 的身份适配。"""
from app.auth.domain.models import Principal
from app.chat.adapters.mysql_pool import MysqlPool, mysql_errors


class MysqlFeishuIdentityResolver:
    def __init__(self, pool: MysqlPool):
        self._pool = pool

    @mysql_errors
    def resolve(self, *, tenant_id: str, app_id: str, open_id: str) -> Principal | None:
        def op(conn):
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT e.user_id, u.username, u.status FROM auth_external_identities e "
                    "JOIN auth_users u ON u.tenant_id=e.tenant_id AND u.user_id=e.user_id "
                    "WHERE e.tenant_id=%s AND e.provider='feishu' AND e.app_id=%s "
                    "AND e.external_id=%s AND e.status='active' LIMIT 1",
                    (tenant_id, app_id, open_id),
                )
                user = cur.fetchone()
                if user is None or user["status"] != "active":
                    return None
                cur.execute(
                    "SELECT r.role_name FROM auth_user_roles ur JOIN auth_roles r "
                    "ON r.tenant_id=ur.tenant_id AND r.role_id=ur.role_id "
                    "WHERE ur.tenant_id=%s AND ur.user_id=%s AND r.status='active'",
                    (tenant_id, user["user_id"]),
                )
                roles = tuple(row["role_name"] for row in cur.fetchall())
                cur.execute(
                    "SELECT department_id FROM auth_user_departments "
                    "WHERE tenant_id=%s AND user_id=%s",
                    (tenant_id, user["user_id"]),
                )
                departments = tuple(row["department_id"] for row in cur.fetchall())
                cur.execute(
                    "SELECT DISTINCT p.permission_code FROM auth_user_roles ur "
                    "JOIN auth_role_permissions rp ON rp.tenant_id=ur.tenant_id "
                    "AND rp.role_id=ur.role_id JOIN auth_permissions p "
                    "ON p.permission_id=rp.permission_id "
                    "WHERE ur.tenant_id=%s AND ur.user_id=%s",
                    (tenant_id, user["user_id"]),
                )
                permissions = tuple(row["permission_code"] for row in cur.fetchall())
            return Principal(tenant_id=tenant_id, user_id=user["user_id"],
                             username=user["username"], roles=roles,
                             department_ids=departments, permissions=permissions)
        return self._pool.run(op)

    def close(self) -> None:
        self._pool.close()
