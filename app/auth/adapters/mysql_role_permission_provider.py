"""Load roles, departments and permission codes from the auth tables."""
from ..application.ports import RolePermissionProvider
from app.chat.adapters.mysql_pool import MysqlPool, mysql_errors


class MysqlRolePermissionProvider(RolePermissionProvider):
    def __init__(self, pool: MysqlPool):
        self._pool = pool

    @mysql_errors
    def load(self, tenant_id: str, user_id: str) -> tuple[
        tuple[str, ...], tuple[str, ...], tuple[str, ...]
    ]:
        def op(conn):
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT r.role_name FROM auth_user_roles ur "
                    "JOIN auth_roles r ON r.tenant_id=ur.tenant_id AND r.role_id=ur.role_id "
                    "WHERE ur.tenant_id=%s AND ur.user_id=%s",
                    (tenant_id, user_id),
                )
                roles = tuple(row["role_name"] for row in cur.fetchall())
                cur.execute(
                    "SELECT d.department_id FROM auth_user_departments d "
                    "WHERE d.tenant_id=%s AND d.user_id=%s",
                    (tenant_id, user_id),
                )
                departments = tuple(row["department_id"] for row in cur.fetchall())
                cur.execute(
                    "SELECT DISTINCT p.permission_code FROM auth_user_roles ur "
                    "JOIN auth_role_permissions rp ON rp.tenant_id=ur.tenant_id "
                    "AND rp.role_id=ur.role_id "
                    "JOIN auth_permissions p ON p.permission_id=rp.permission_id "
                    "WHERE ur.tenant_id=%s AND ur.user_id=%s",
                    (tenant_id, user_id),
                )
                permissions = tuple(row["permission_code"] for row in cur.fetchall())
            return roles, departments, permissions
        return self._pool.run(op)