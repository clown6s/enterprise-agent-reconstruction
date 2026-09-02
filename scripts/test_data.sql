-- ============================================================
-- 企业智能体测试数据（仅供手动执行）
-- 目标租户：tenant-test；目标用户：user-test-001
-- 可重复执行：演示业务表使用 CREATE IF NOT EXISTS，数据使用唯一键。
-- 不包含任何真实密码、Token 或外部服务密钥。
-- ============================================================

SET NAMES utf8mb4;
START TRANSACTION;

-- ---------- 1. 确保测试用户具备 Chat/SOP/NL2SQL 权限 ----------

INSERT IGNORE INTO auth_permissions (permission_id, permission_code, description)
VALUES
    ('perm-chat', 'chat:ask', '使用 Chat 问答'),
    ('perm-sop-read', 'sop:read', '查看 SOP'),
    ('perm-sop-execute', 'sop:execute', '执行已授权的 SOP 动作'),
    ('perm-sql-read', 'sql:read', '执行只读数据查询'),
    ('perm-schema-admin', 'schema:admin', '管理 NL2SQL Schema Registry');

INSERT IGNORE INTO auth_roles
    (tenant_id, role_id, role_name, description, status)
VALUES
    ('tenant-test', 'role-employee', 'employee', '测试普通员工', 'active'),
    ('tenant-test', 'role-schema-admin', 'schema-admin', '测试 Schema 管理员', 'active');

INSERT IGNORE INTO auth_user_roles (tenant_id, user_id, role_id)
VALUES
    ('tenant-test', 'user-test-001', 'role-employee'),
    ('tenant-test', 'user-test-001', 'role-schema-admin');

INSERT IGNORE INTO auth_role_permissions (tenant_id, role_id, permission_id)
VALUES
    ('tenant-test', 'role-employee', 'perm-chat'),
    ('tenant-test', 'role-employee', 'perm-sop-read'),
    ('tenant-test', 'role-employee', 'perm-sql-read'),
    ('tenant-test', 'role-schema-admin', 'perm-schema-admin');

-- ---------- 2. NL2SQL 演示业务表 ----------
-- 这些表是测试业务数据，不是系统元数据表。

CREATE TABLE IF NOT EXISTS orders (
    tenant_id VARCHAR(64) NOT NULL,
    order_id VARCHAR(64) NOT NULL,
    customer_name VARCHAR(128) NOT NULL,
    region VARCHAR(32) NOT NULL,
    category VARCHAR(64) NOT NULL,
    amount DECIMAL(14,2) NOT NULL,
    status ENUM('paid', 'pending', 'cancelled', 'refunded') NOT NULL,
    created_at DATETIME NOT NULL,
    PRIMARY KEY (tenant_id, order_id),
    KEY idx_orders_tenant_date (tenant_id, created_at),
    KEY idx_orders_tenant_region (tenant_id, region),
    KEY idx_orders_tenant_status (tenant_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS procurement_requests (
    tenant_id VARCHAR(64) NOT NULL,
    request_id VARCHAR(64) NOT NULL,
    applicant_id VARCHAR(64) NOT NULL,
    department_id VARCHAR(64) NOT NULL,
    region VARCHAR(32) NOT NULL,
    item_name VARCHAR(128) NOT NULL,
    quantity INT UNSIGNED NOT NULL,
    budget DECIMAL(14,2) NOT NULL,
    status ENUM('draft', 'submitted', 'approved', 'rejected', 'ordered') NOT NULL,
    created_at DATETIME NOT NULL,
    PRIMARY KEY (tenant_id, request_id),
    KEY idx_procurement_tenant_date (tenant_id, created_at),
    KEY idx_procurement_tenant_department (tenant_id, department_id),
    KEY idx_procurement_tenant_status (tenant_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 120 条订单：覆盖 2025-01 至 2026-08、华东/华南/华北/西部、不同金额和状态。
INSERT INTO orders
    (tenant_id, order_id, customer_name, region, category, amount, status, created_at)
SELECT
    'tenant-test',
    CONCAT('ORD-', LPAD(seq, 5, '0')),
    CONCAT('测试客户-', MOD(seq - 1, 24) + 1),
    ELT(MOD(seq - 1, 4) + 1, '华东', '华南', '华北', '西部'),
    ELT(MOD(seq - 1, 5) + 1, '软件', '硬件', '服务', '咨询', '订阅'),
    CASE MOD(seq, 10)
        WHEN 0 THEN 150000.00
        WHEN 1 THEN 120000.00
        WHEN 2 THEN 98000.00
        WHEN 3 THEN 76000.00
        WHEN 4 THEN 52000.00
        ELSE 8000.00 + MOD(seq * 1379, 42000)
    END,
    ELT(MOD(seq - 1, 4) + 1, 'paid', 'pending', 'paid', 'refunded'),
    DATE_ADD('2025-01-05 09:00:00', INTERVAL (seq * 6) DAY)
FROM (
    SELECT ones.n + tens.n * 10 + hundreds.n * 100 + 1 AS seq
    FROM
        (SELECT 0 n UNION ALL SELECT 1 UNION ALL SELECT 2 UNION ALL SELECT 3 UNION ALL SELECT 4
         UNION ALL SELECT 5 UNION ALL SELECT 6 UNION ALL SELECT 7 UNION ALL SELECT 8 UNION ALL SELECT 9) ones
    CROSS JOIN
        (SELECT 0 n UNION ALL SELECT 1 UNION ALL SELECT 2 UNION ALL SELECT 3 UNION ALL SELECT 4
         UNION ALL SELECT 5 UNION ALL SELECT 6 UNION ALL SELECT 7 UNION ALL SELECT 8 UNION ALL SELECT 9) tens
    CROSS JOIN
        (SELECT 0 n UNION ALL SELECT 1) hundreds
) numbers
ON DUPLICATE KEY UPDATE
    customer_name = VALUES(customer_name), region = VALUES(region),
    category = VALUES(category), amount = VALUES(amount),
    status = VALUES(status), created_at = VALUES(created_at);

-- 80 条采购申请：覆盖申请人、部门、地区、预算和审批状态。
INSERT INTO procurement_requests
    (tenant_id, request_id, applicant_id, department_id, region,
     item_name, quantity, budget, status, created_at)
SELECT
    'tenant-test',
    CONCAT('PR-', LPAD(seq, 5, '0')),
    CONCAT('user-', LPAD(MOD(seq - 1, 12) + 1, 3, '0')),
    ELT(MOD(seq - 1, 4) + 1, 'dept-tech', 'dept-sales', 'dept-finance', 'dept-ops'),
    ELT(MOD(seq - 1, 4) + 1, '华东', '华南', '华北', '西部'),
    ELT(MOD(seq - 1, 6) + 1, '显示器', '服务器', '软件许可', '办公用品', '培训服务', '云资源'),
    1 + MOD(seq, 20),
    CASE MOD(seq, 8)
        WHEN 0 THEN 180000.00
        WHEN 1 THEN 120000.00
        WHEN 2 THEN 95000.00
        ELSE 3000.00 + MOD(seq * 2137, 70000)
    END,
    ELT(MOD(seq - 1, 5) + 1, 'submitted', 'approved', 'ordered', 'rejected', 'submitted'),
    DATE_ADD('2025-03-01 10:00:00', INTERVAL (seq * 5) DAY)
FROM (
    SELECT ones.n + tens.n * 10 + 1 AS seq
    FROM
        (SELECT 0 n UNION ALL SELECT 1 UNION ALL SELECT 2 UNION ALL SELECT 3 UNION ALL SELECT 4
         UNION ALL SELECT 5 UNION ALL SELECT 6 UNION ALL SELECT 7 UNION ALL SELECT 8 UNION ALL SELECT 9) ones
    CROSS JOIN
        (SELECT 0 n UNION ALL SELECT 1 UNION ALL SELECT 2 UNION ALL SELECT 3 UNION ALL SELECT 4
         UNION ALL SELECT 5 UNION ALL SELECT 6 UNION ALL SELECT 7) tens
) numbers
ON DUPLICATE KEY UPDATE
    applicant_id = VALUES(applicant_id), department_id = VALUES(department_id),
    region = VALUES(region), item_name = VALUES(item_name), quantity = VALUES(quantity),
    budget = VALUES(budget), status = VALUES(status), created_at = VALUES(created_at);

-- ---------- 3. Schema Catalog：让 NL2SQL 只看到白名单 ----------

INSERT IGNORE INTO sql_data_domains
    (tenant_id, domain_id, domain_name, description, status,
     default_time_column, max_rows, max_execution_seconds, created_by, updated_by)
VALUES
    ('tenant-test', 'domain-orders', 'orders',
     '订单和销售数据，可查询订单数量、订单金额、地区、类别、状态和创建时间。',
     'active', 'created_at', 1000, 10, 'user-test-001', 'user-test-001'),
    ('tenant-test', 'domain-procurement', 'procurement',
     '采购申请数据，可查询采购申请数量、预算、地区、部门、审批状态和创建时间。',
     'active', 'created_at', 1000, 10, 'user-test-001', 'user-test-001');

INSERT IGNORE INTO sql_allowed_tables
    (tenant_id, domain_id, table_name, table_description, required_tenant_filter)
VALUES
    ('tenant-test', 'domain-orders', 'orders', '订单主表', TRUE),
    ('tenant-test', 'domain-procurement', 'procurement_requests', '采购申请主表', TRUE);

INSERT IGNORE INTO sql_allowed_columns
    (tenant_id, domain_id, table_name, column_name, business_name, data_type,
     selectable, filterable, sortable, aggregatable, sensitive, description)
VALUES
    ('tenant-test', 'domain-orders', 'orders', 'order_id', '订单编号', 'varchar', TRUE, TRUE, FALSE, FALSE, FALSE, '订单唯一编号'),
    ('tenant-test', 'domain-orders', 'orders', 'customer_name', '客户名称', 'varchar', TRUE, TRUE, TRUE, FALSE, FALSE, '测试客户名称'),
    ('tenant-test', 'domain-orders', 'orders', 'region', '地区', 'varchar', TRUE, TRUE, TRUE, FALSE, FALSE, '销售地区'),
    ('tenant-test', 'domain-orders', 'orders', 'category', '类别', 'varchar', TRUE, TRUE, TRUE, FALSE, FALSE, '商品类别'),
    ('tenant-test', 'domain-orders', 'orders', 'amount', '订单金额', 'decimal', TRUE, TRUE, TRUE, TRUE, FALSE, '订单金额'),
    ('tenant-test', 'domain-orders', 'orders', 'status', '订单状态', 'enum', TRUE, TRUE, TRUE, FALSE, FALSE, '订单状态'),
    ('tenant-test', 'domain-orders', 'orders', 'created_at', '创建时间', 'datetime', TRUE, TRUE, TRUE, FALSE, FALSE, '订单创建时间'),
    ('tenant-test', 'domain-procurement', 'procurement_requests', 'request_id', '申请编号', 'varchar', TRUE, TRUE, FALSE, FALSE, FALSE, '采购申请编号'),
    ('tenant-test', 'domain-procurement', 'procurement_requests', 'applicant_id', '申请人', 'varchar', TRUE, TRUE, TRUE, FALSE, FALSE, '申请人编号'),
    ('tenant-test', 'domain-procurement', 'procurement_requests', 'department_id', '部门', 'varchar', TRUE, TRUE, TRUE, FALSE, FALSE, '申请部门'),
    ('tenant-test', 'domain-procurement', 'procurement_requests', 'region', '地区', 'varchar', TRUE, TRUE, TRUE, FALSE, FALSE, '申请地区'),
    ('tenant-test', 'domain-procurement', 'procurement_requests', 'item_name', '物品名称', 'varchar', TRUE, TRUE, TRUE, FALSE, FALSE, '采购物品'),
    ('tenant-test', 'domain-procurement', 'procurement_requests', 'quantity', '数量', 'int', TRUE, TRUE, TRUE, TRUE, FALSE, '采购数量'),
    ('tenant-test', 'domain-procurement', 'procurement_requests', 'budget', '预算', 'decimal', TRUE, TRUE, TRUE, TRUE, FALSE, '采购预算'),
    ('tenant-test', 'domain-procurement', 'procurement_requests', 'status', '申请状态', 'enum', TRUE, TRUE, TRUE, FALSE, FALSE, '审批/采购状态'),
    ('tenant-test', 'domain-procurement', 'procurement_requests', 'created_at', '创建时间', 'datetime', TRUE, TRUE, TRUE, FALSE, FALSE, '申请创建时间');

INSERT IGNORE INTO sql_domain_permissions
    (tenant_id, domain_id, subject_type, subject_id, row_predicate_template, allowed)
VALUES
    ('tenant-test', 'domain-orders', 'user', 'user-test-001', 'tenant_id = :tenant_id', TRUE),
    ('tenant-test', 'domain-procurement', 'user', 'user-test-001', 'tenant_id = :tenant_id', TRUE);

-- ---------- 4. SOP 测试定义、版本和步骤 ----------

INSERT IGNORE INTO sop_definitions
    (tenant_id, sop_id, title, scope, status, current_version,
     created_by, updated_by)
VALUES
    ('tenant-test', 'expense_claim', '报销流程', '费用报销', 'published', 'v1',
     'user-test-001', 'user-test-001'),
    ('tenant-test', 'procurement', '采购申请流程', '采购管理', 'published', 'v1',
     'user-test-001', 'user-test-001');

INSERT IGNORE INTO sop_versions
    (tenant_id, sop_id, version, version_status, effective_from,
     description, definition_hash, definition_json, created_by, published_by, published_at)
VALUES
    ('tenant-test', 'expense_claim', 'v1', 'published', '2026-01-01 00:00:00',
     '测试报销流程 v1', SHA2('expense_claim:v1', 256),
     '{"roles":["employee","manager","finance"],"steps":[{"step_id":"s1"},{"step_id":"s2"},{"step_id":"s3"}]}',
     'user-test-001', 'user-test-001', CURRENT_TIMESTAMP(6)),
    ('tenant-test', 'procurement', 'v1', 'published', '2026-01-01 00:00:00',
     '测试采购申请流程 v1', SHA2('procurement:v1', 256),
     '{"roles":["employee","manager","finance"],"steps":[{"step_id":"p1"},{"step_id":"p2"},{"step_id":"p3"}]}',
     'user-test-001', 'user-test-001', CURRENT_TIMESTAMP(6));

INSERT IGNORE INTO sop_steps
    (tenant_id, sop_id, version, step_id, sequence_no, instruction,
     preconditions, inputs, next_steps, warnings, role_required,
     requires_confirmation, action_name, action_schema)
VALUES
    ('tenant-test', 'expense_claim', 'v1', 's1', 1, '提交报销申请，附发票和审批单',
     '["已发生合规费用"]', '["发票","事由","金额"]', '["s2"]', '[]', 'employee', FALSE, NULL, NULL),
    ('tenant-test', 'expense_claim', 'v1', 's2', 2, '部门负责人审批',
     '[]', '["审批意见"]', '["s3"]', '[]', 'manager', FALSE, NULL, NULL),
    ('tenant-test', 'expense_claim', 'v1', 's3', 3, '财务复核并打款',
     '[]', '["付款账户"]', '[]', '["涉及资金支付"]', 'finance', TRUE, 'expense_payment', '{"type":"object"}'),
    ('tenant-test', 'procurement', 'v1', 'p1', 1, '填写采购申请（品名、数量、预算）',
     '[]', '["品名","数量","预算"]', '["p2"]', '[]', 'employee', FALSE, NULL, NULL),
    ('tenant-test', 'procurement', 'v1', 'p2', 2, '预算负责人审批',
     '[]', '["审批意见"]', '["p3"]', '[]', 'manager', FALSE, NULL, NULL),
    ('tenant-test', 'procurement', 'v1', 'p3', 3, '下单采购',
     '[]', '[]', '[]', '["产生采购支出"]', 'finance', TRUE, 'create_purchase_order', '{"type":"object"}');

COMMIT;

-- ---------- 5. 执行后检查 ----------
-- SELECT COUNT(*) AS order_count FROM orders WHERE tenant_id='tenant-test';
-- SELECT COUNT(*) AS procurement_count FROM procurement_requests WHERE tenant_id='tenant-test';
-- SELECT * FROM sql_data_domains WHERE tenant_id='tenant-test';
-- SELECT * FROM sop_definitions WHERE tenant_id='tenant-test';
-- SELECT ur.user_id, p.permission_code
-- FROM auth_user_roles ur
-- JOIN auth_role_permissions rp ON rp.tenant_id=ur.tenant_id AND rp.role_id=ur.role_id
-- JOIN auth_permissions p ON p.permission_id=rp.permission_id
-- WHERE ur.tenant_id='tenant-test' AND ur.user_id='user-test-001';
