"""真实 MySQL 连通性冒烟脚本：Registry 登记 -> 发布 -> Catalog 读取。

用法（需先执行 scripts/chat_schema.sql 与 scripts/test_data.sql）::

    python scripts/smoke_schema_registry.py

依赖环境变量（与 app/chat/bootstrap/config.py 相同）::

    CHAT_MYSQL_HOST / CHAT_MYSQL_PORT / CHAT_MYSQL_USER / CHAT_MYSQL_PASSWORD / CHAT_MYSQL_DB

流程：
1. 用 ``MysqlSchemaRegistry`` 探测业务表 ``orders`` 的真实字段。
2. 登记一个临时域 + 表 + 列，发布为 active。
3. 用 ``MysqlSchemaCatalog`` 验证已发布域可被 describe/allowed_tables 读取。
4. 清理临时域，验证发布后可回滚（域从 catalog 消失）。

退出码：0 表示链路可用；非 0 表示某一环失败。
"""
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

# 与主应用一致：自动读取项目根目录 .env；命令行环境变量仍优先。
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

# 让 ``app`` 包可被导入（脚本位于 scripts/ 下）。
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.chat.adapters.mysql_pool import MysqlPool
from app.chat.adapters.mysql_schema_catalog import MysqlSchemaCatalog
from app.chat.adapters.mysql_schema_registry import MysqlSchemaRegistry
from app.chat.application.context import RequestContext
from app.chat.application.schema_registry import (
    SchemaColumn, SchemaDomain, SchemaRegistry, SchemaTable,
)

TENANT = os.getenv("SMOKE_TENANT", "tenant-test")
USER = os.getenv("SMOKE_USER", "user-test-001")
DOMAIN_NAME = f"smoke_{int(time.time())}"


def _admin_context() -> RequestContext:
    return RequestContext(tenant_id=TENANT, user_id=USER, authenticated=True,
                          permissions=("schema:admin",))


def _pool() -> MysqlPool:
    return MysqlPool(
        host=os.getenv("CHAT_MYSQL_HOST", os.getenv("MYSQL_HOST", "127.0.0.1")),
        port=int(os.getenv("CHAT_MYSQL_PORT", os.getenv("MYSQL_PORT", "3306"))),
        user=os.getenv("CHAT_MYSQL_USER", os.getenv("MYSQL_USER", "root")),
        password=os.getenv("CHAT_MYSQL_PASSWORD",
                            os.getenv("MYSQL_PASSWORD", os.getenv("MYSQL_ROOT_PASSWORD", ""))),
        database=os.getenv("CHAT_MYSQL_DB", os.getenv("MYSQL_DB", "enterprise_agent")),
    )


def _cleanup(pool: MysqlPool, domain_id: str) -> None:
    """删除临时域，保证脚本可重复执行。"""
    def op(conn):
        with conn.cursor() as c:
            c.execute("DELETE l FROM sql_schema_change_logs l JOIN sql_schema_versions v ON v.tenant_id=l.tenant_id AND v.version_id=l.version_id WHERE l.tenant_id=%s AND l.domain_id=%s", (TENANT, domain_id))
            c.execute("DELETE j FROM sql_allowed_joins j JOIN sql_schema_versions v ON v.tenant_id=j.tenant_id AND v.version_id=j.version_id WHERE j.tenant_id=%s AND v.domain_id=%s", (TENANT, domain_id))
            c.execute("DELETE FROM sql_schema_versions WHERE tenant_id=%s AND domain_id=%s", (TENANT, domain_id))
            c.execute("DELETE FROM sql_domain_permissions WHERE tenant_id=%s AND domain_id=%s",
                      (TENANT, domain_id))
            c.execute("DELETE FROM sql_allowed_columns WHERE tenant_id=%s AND domain_id=%s",
                      (TENANT, domain_id))
            c.execute("DELETE FROM sql_allowed_tables WHERE tenant_id=%s AND domain_id=%s",
                      (TENANT, domain_id))
            c.execute("DELETE FROM sql_domain_keywords WHERE tenant_id=%s AND domain_id=%s",
                      (TENANT, domain_id))
            c.execute("DELETE FROM sql_data_domains WHERE tenant_id=%s AND domain_id=%s",
                      (TENANT, domain_id))
        conn.commit()
    pool.run(op)


def main() -> int:
    pool = _pool()
    registry = SchemaRegistry(MysqlSchemaRegistry(pool))
    catalog = MysqlSchemaCatalog(pool)
    ctx = _admin_context()
    domain_id = DOMAIN_NAME

    try:
        # 1. 真实表探测：只允许单段标识符。
        print("[1/5] introspect orders ...")
        candidates = {r["table_name"]: r["columns"]
                      for r in registry.introspect(context=ctx, tables=["orders"])}
        if "orders" not in candidates or not candidates["orders"]:
            print("  !!! 未探测到 orders 表，请确认已执行 scripts/test_data.sql")
            return 2
        print(f"  orders 列数={len(candidates['orders'])}")

        # 2. 登记临时域 + 表 + 列（全为 draft）。
        print("[2/5] register domain/table/columns ...")
        registry.register_domain(
            SchemaDomain(domain_id=domain_id, domain_name=DOMAIN_NAME,
                         description="smoke registry domain", keywords=(DOMAIN_NAME,)),
            context=ctx)
        registry.register_table(domain_id, SchemaTable("orders", description="smoke 订单表"),
                                context=ctx)
        columns = [
            SchemaColumn(col["column_name"], col["data_type"], business_name=col["column_name"],
                         selectable=True)
            for col in candidates["orders"]
            if col["column_name"] not in ("tenant_id",)
        ]
        registry.register_columns(domain_id, "orders", columns, context=ctx)

        # 3. 发布（校验后置 active，写入版本 + 变更日志）。
        print("[3/5] publish ...")
        pub = registry.publish(domain_id, context=ctx, reason="smoke 发布")
        if not pub or not pub.get("snapshot_hash"):
            print("  !!! 发布未返回版本快照")
            return 3
        print(f"  version_no={pub.get('version_no')} hash={pub['snapshot_hash'][:12]}...")
        before = set(catalog.domains(context=ctx))
        if DOMAIN_NAME not in before:
            print("  !!! 发布后 catalog 未读到该域")
            return 3
        print(f"  已发布域总数={len(before)}")

        # 4. 用 NL2SQL 使用的 catalog 读取已发布元数据。
        print("[4/5] catalog describe/allowed_tables ...")
        desc = catalog.describe(DOMAIN_NAME, context=ctx)
        allowed = catalog.allowed_tables(DOMAIN_NAME, context=ctx)
        if not desc or "orders" not in allowed:
            print("  !!! catalog 读取已发布元数据失败")
            return 4
        print(f"  describe 行数={len(desc.splitlines())} allowed={sorted(allowed)}")

        # 5. 清理临时域并确认不可再读。
        print("[5/5] cleanup ...")
        _cleanup(pool, domain_id)
        after = catalog.domains(context=ctx)
        if DOMAIN_NAME in after:
            print("  !!! 清理失败，域仍可读")
            return 5
        print("  cleanup ok")
        print("\nOK: Schema Registry 全链路可用（真实 MySQL）。")
        return 0
    except Exception as exc:  # noqa: BLE001 - smoke 脚本汇总任意错误
        print(f"\nFAIL: {type(exc).__name__}: {exc}")
        try:
            _cleanup(pool, domain_id)
        except Exception:  # noqa: BLE001
            pass
        return 1
    finally:
        pool.close()


if __name__ == "__main__":
    sys.exit(main())
