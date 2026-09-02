-- ============================================================
-- Chat / SOP / NL2SQL / Auth 建表脚本（一次执行全部）
-- 依赖：已有 ingestion_documents 表（sop_versions 仅引用其 document_id，不建外键）
-- 引擎：InnoDB；字符集：utf8mb4
--
-- 多租户设计约定：
--  * 所有业务主键均包含 tenant_id 联合键，杜绝跨租户 id 冲突。
--  * 关联表的外键一律带 tenant_id，杜绝跨租户关联。
--  * 密码 / token 只存哈希，禁止明文。
-- ============================================================

-- ============================================================
-- 0. 身份、租户与授权
-- ============================================================

CREATE TABLE IF NOT EXISTS auth_tenants (
    tenant_id VARCHAR(64) NOT NULL,
    tenant_name VARCHAR(255) NOT NULL,
    status ENUM('active', 'disabled') NOT NULL DEFAULT 'active',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (tenant_id),
    UNIQUE KEY uk_auth_tenant_name (tenant_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS auth_users (
    tenant_id VARCHAR(64) NOT NULL,
    user_id VARCHAR(64) NOT NULL,
    username VARCHAR(128) NOT NULL,
    email VARCHAR(255) NULL,
    display_name VARCHAR(255) NULL,
    password_hash VARCHAR(255) NULL,
    status ENUM('active', 'locked', 'disabled') NOT NULL DEFAULT 'active',
    failed_login_count INT UNSIGNED NOT NULL DEFAULT 0,
    locked_until DATETIME(6) NULL,
    last_login_at DATETIME(6) NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (tenant_id, user_id),
    UNIQUE KEY uk_auth_user_tenant_username (tenant_id, username),
    UNIQUE KEY uk_auth_user_tenant_email (tenant_id, email),
    KEY idx_auth_user_tenant_status (tenant_id, status),
    CONSTRAINT fk_auth_user_tenant FOREIGN KEY (tenant_id)
        REFERENCES auth_tenants(tenant_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS auth_departments (
    tenant_id VARCHAR(64) NOT NULL,
    department_id VARCHAR(64) NOT NULL,
    parent_department_id VARCHAR(64) NULL,
    department_name VARCHAR(255) NOT NULL,
    status ENUM('active', 'disabled') NOT NULL DEFAULT 'active',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (tenant_id, department_id),
    UNIQUE KEY uk_auth_department_name (tenant_id, department_name),
    CONSTRAINT fk_auth_department_tenant FOREIGN KEY (tenant_id)
        REFERENCES auth_tenants(tenant_id),
    CONSTRAINT fk_auth_department_parent FOREIGN KEY (tenant_id, parent_department_id)
        REFERENCES auth_departments(tenant_id, department_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS auth_user_departments (
    tenant_id VARCHAR(64) NOT NULL,
    user_id VARCHAR(64) NOT NULL,
    department_id VARCHAR(64) NOT NULL,
    is_primary BOOLEAN NOT NULL DEFAULT FALSE,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (tenant_id, user_id, department_id),
    KEY idx_auth_ud_department (tenant_id, department_id, user_id),
    CONSTRAINT fk_auth_ud_user FOREIGN KEY (tenant_id, user_id)
        REFERENCES auth_users(tenant_id, user_id),
    CONSTRAINT fk_auth_ud_department FOREIGN KEY (tenant_id, department_id)
        REFERENCES auth_departments(tenant_id, department_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS auth_roles (
    tenant_id VARCHAR(64) NOT NULL,
    role_id VARCHAR(64) NOT NULL,
    role_name VARCHAR(128) NOT NULL,
    description VARCHAR(500) NULL,
    status ENUM('active', 'disabled') NOT NULL DEFAULT 'active',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (tenant_id, role_id),
    UNIQUE KEY uk_auth_role_name (tenant_id, role_name),
    CONSTRAINT fk_auth_role_tenant FOREIGN KEY (tenant_id)
        REFERENCES auth_tenants(tenant_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS auth_user_roles (
    tenant_id VARCHAR(64) NOT NULL,
    user_id VARCHAR(64) NOT NULL,
    role_id VARCHAR(64) NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (tenant_id, user_id, role_id),
    KEY idx_auth_user_role_role (tenant_id, role_id, user_id),
    CONSTRAINT fk_auth_ur_user FOREIGN KEY (tenant_id, user_id)
        REFERENCES auth_users(tenant_id, user_id),
    CONSTRAINT fk_auth_ur_role FOREIGN KEY (tenant_id, role_id)
        REFERENCES auth_roles(tenant_id, role_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS auth_permissions (
    permission_id VARCHAR(64) NOT NULL,
    permission_code VARCHAR(128) NOT NULL,
    description VARCHAR(500) NULL,
    PRIMARY KEY (permission_id),
    UNIQUE KEY uk_auth_permission_code (permission_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS auth_role_permissions (
    tenant_id VARCHAR(64) NOT NULL,
    role_id VARCHAR(64) NOT NULL,
    permission_id VARCHAR(64) NOT NULL,
    PRIMARY KEY (tenant_id, role_id, permission_id),
    CONSTRAINT fk_auth_rp_role FOREIGN KEY (tenant_id, role_id)
        REFERENCES auth_roles(tenant_id, role_id),
    CONSTRAINT fk_auth_rp_permission FOREIGN KEY (permission_id)
        REFERENCES auth_permissions(permission_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS auth_sessions (
    tenant_id VARCHAR(64) NOT NULL,
    session_id CHAR(36) NOT NULL,
    access_token_hash CHAR(64) NULL,
    refresh_token_hash CHAR(64) NULL,
    user_id VARCHAR(64) NOT NULL,
    client_ip VARBINARY(16) NULL,
    user_agent VARCHAR(512) NULL,
    status ENUM('active', 'revoked', 'expired') NOT NULL DEFAULT 'active',
    expires_at DATETIME(6) NOT NULL,
    access_token_expires_at DATETIME(6) NULL,
    last_seen_at DATETIME(6) NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    revoked_at DATETIME(6) NULL,
    PRIMARY KEY (tenant_id, session_id),
    UNIQUE KEY uk_auth_session_access_hash (access_token_hash),
    UNIQUE KEY uk_auth_session_refresh_hash (refresh_token_hash),
    KEY idx_auth_session_access_expire (access_token_hash, status, access_token_expires_at),
    KEY idx_auth_session_user_status (tenant_id, user_id, status),
    KEY idx_auth_session_expire (expires_at),
    CONSTRAINT fk_auth_session_user FOREIGN KEY (tenant_id, user_id)
        REFERENCES auth_users(tenant_id, user_id),
    CONSTRAINT fk_auth_session_tenant FOREIGN KEY (tenant_id)
        REFERENCES auth_tenants(tenant_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS auth_api_tokens (
    tenant_id VARCHAR(64) NOT NULL,
    token_id VARCHAR(64) NOT NULL,
    token_hash CHAR(64) NOT NULL,
    token_name VARCHAR(255) NOT NULL,
    user_id VARCHAR(64) NULL,
    scopes JSON NOT NULL,
    status ENUM('active', 'revoked') NOT NULL DEFAULT 'active',
    expires_at DATETIME(6) NULL,
    last_used_at DATETIME(6) NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    revoked_at DATETIME(6) NULL,
    PRIMARY KEY (tenant_id, token_id),
    UNIQUE KEY uk_auth_api_token_hash (token_hash),
    KEY idx_auth_api_token_status (tenant_id, status, expires_at),
    CONSTRAINT fk_auth_api_token_tenant FOREIGN KEY (tenant_id)
        REFERENCES auth_tenants(tenant_id),
    CONSTRAINT fk_auth_api_token_user FOREIGN KEY (tenant_id, user_id)
        REFERENCES auth_users(tenant_id, user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ============================================================
-- 1. 会话
-- ============================================================

CREATE TABLE IF NOT EXISTS chat_conversations (
    tenant_id VARCHAR(64) NOT NULL,
    conversation_id CHAR(36) NOT NULL,
    user_id VARCHAR(64) NOT NULL,

    title VARCHAR(255) NULL,
    status ENUM('active', 'archived', 'deleted') NOT NULL DEFAULT 'active',

    last_intent VARCHAR(32) NULL,
    last_mode VARCHAR(32) NULL,

    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    expires_at DATETIME(6) NULL,

    PRIMARY KEY (tenant_id, conversation_id),
    KEY idx_chat_conv_user_updated (tenant_id, user_id, updated_at),
    KEY idx_chat_conv_expire (expires_at),
    KEY idx_chat_conv_status (tenant_id, status),
    CONSTRAINT fk_chat_conv_user FOREIGN KEY (tenant_id, user_id)
        REFERENCES auth_users(tenant_id, user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS chat_messages (
    tenant_id VARCHAR(64) NOT NULL,
    message_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    conversation_id CHAR(36) NOT NULL,

    seq_no INT UNSIGNED NOT NULL,
    role ENUM('system', 'user', 'assistant', 'tool') NOT NULL,
    content MEDIUMTEXT NOT NULL,

    mode VARCHAR(32) NULL,
    trust_level ENUM('trusted', 'untrusted') NOT NULL DEFAULT 'untrusted',
    security_flags JSON NULL,

    token_count INT UNSIGNED NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),

    PRIMARY KEY (message_id),
    UNIQUE KEY uk_chat_message_seq (tenant_id, conversation_id, seq_no),
    KEY idx_chat_message_conversation (tenant_id, conversation_id, created_at),
    CONSTRAINT fk_chat_message_conversation
        FOREIGN KEY (tenant_id, conversation_id)
        REFERENCES chat_conversations(tenant_id, conversation_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS chat_message_citations (
    citation_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    message_id BIGINT UNSIGNED NOT NULL,

    citation_no SMALLINT UNSIGNED NOT NULL,
    source_type ENUM('document', 'sop', 'sql_result') NOT NULL,

    document_id VARCHAR(64) NULL,
    chunk_id VARCHAR(128) NULL,
    page INT NULL,

    sop_id VARCHAR(64) NULL,
    sop_version VARCHAR(32) NULL,
    step_id VARCHAR(64) NULL,

    query_id CHAR(36) NULL,
    title VARCHAR(255) NULL,

    PRIMARY KEY (citation_id),
    UNIQUE KEY uk_message_citation_no (message_id, citation_no),
    KEY idx_citation_document (document_id, chunk_id),
    KEY idx_citation_sop (sop_id, sop_version, step_id),
    KEY idx_citation_query (query_id),
    CONSTRAINT fk_citation_message
        FOREIGN KEY (message_id)
        REFERENCES chat_messages(message_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS chat_feedback (
    feedback_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    tenant_id VARCHAR(64) NOT NULL,
    user_id VARCHAR(64) NOT NULL,
    message_id BIGINT UNSIGNED NOT NULL,

    rating ENUM('like', 'dislike') NOT NULL,
    comment VARCHAR(2000) NULL,
    accepted BOOLEAN NULL,
    reasons JSON NULL,

    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),

    PRIMARY KEY (feedback_id),
    KEY idx_chat_feedback_message (message_id),
    KEY idx_chat_feedback_user_time (tenant_id, user_id, created_at),
    CONSTRAINT fk_chat_feedback_user FOREIGN KEY (tenant_id, user_id)
        REFERENCES auth_users(tenant_id, user_id),
    CONSTRAINT fk_chat_feedback_message FOREIGN KEY (message_id)
        REFERENCES chat_messages(message_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ============================================================
-- 2. 内容安全与注入审计
-- ============================================================

CREATE TABLE IF NOT EXISTS security_content_flags (
    flag_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    tenant_id VARCHAR(64) NOT NULL,

    content_type ENUM('document', 'message', 'sop_text', 'sql_result') NOT NULL,
    content_ref VARCHAR(128) NULL,
    message_id BIGINT UNSIGNED NULL,
    document_id VARCHAR(64) NULL,

    risk_level ENUM('low', 'medium', 'high') NOT NULL DEFAULT 'low',
    matched_flags JSON NULL,
    action_taken ENUM('allowed', 'excluded', 'quarantined', 'rejected') NOT NULL,
    detail VARCHAR(2000) NULL,

    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),

    PRIMARY KEY (flag_id),
    KEY idx_security_flag_content (tenant_id, content_type, content_ref),
    KEY idx_security_flag_risk (tenant_id, risk_level, created_at),
    KEY idx_security_flag_action (action_taken, created_at),
    CONSTRAINT fk_security_flag_message FOREIGN KEY (message_id)
        REFERENCES chat_messages(message_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ============================================================
-- 3. SOP 定义与版本
-- ============================================================

CREATE TABLE IF NOT EXISTS sop_definitions (
    tenant_id VARCHAR(64) NOT NULL,
    sop_id VARCHAR(64) NOT NULL,

    title VARCHAR(255) NOT NULL,
    scope VARCHAR(255) NULL,
    status ENUM('draft', 'published', 'retired') NOT NULL DEFAULT 'draft',

    current_version VARCHAR(32) NULL,

    created_by VARCHAR(64) NOT NULL,
    updated_by VARCHAR(64) NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),

    PRIMARY KEY (tenant_id, sop_id),
    KEY idx_sop_tenant_status (tenant_id, status),
    KEY idx_sop_title (tenant_id, title),
    CONSTRAINT fk_sop_definition_tenant FOREIGN KEY (tenant_id)
        REFERENCES auth_tenants(tenant_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS sop_versions (
    tenant_id VARCHAR(64) NOT NULL,
    sop_id VARCHAR(64) NOT NULL,
    version VARCHAR(32) NOT NULL,

    version_status ENUM('draft', 'published', 'retired') NOT NULL DEFAULT 'draft',

    effective_from DATETIME(6) NULL,
    effective_to DATETIME(6) NULL,

    description TEXT NULL,
    source_document_id VARCHAR(64) NULL,
    source_document_hash CHAR(64) NULL,

    definition_hash CHAR(64) NOT NULL,
    definition_json JSON NOT NULL,

    created_by VARCHAR(64) NOT NULL,
    published_by VARCHAR(64) NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    published_at DATETIME(6) NULL,

    PRIMARY KEY (tenant_id, sop_id, version),
    KEY idx_sop_version_active (tenant_id, version_status, effective_from, effective_to),
    KEY idx_sop_version_document (source_document_id),
    CONSTRAINT fk_sop_version_definition
        FOREIGN KEY (tenant_id, sop_id)
        REFERENCES sop_definitions(tenant_id, sop_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS sop_steps (
    tenant_id VARCHAR(64) NOT NULL,
    sop_id VARCHAR(64) NOT NULL,
    version VARCHAR(32) NOT NULL,
    step_id VARCHAR(64) NOT NULL,

    sequence_no INT NOT NULL,
    instruction TEXT NOT NULL,

    preconditions JSON NULL,
    inputs JSON NULL,
    next_steps JSON NULL,
    warnings JSON NULL,

    role_required VARCHAR(64) NULL,
    requires_confirmation BOOLEAN NOT NULL DEFAULT FALSE,
    action_name VARCHAR(128) NULL,
    action_schema JSON NULL,

    PRIMARY KEY (tenant_id, sop_id, version, step_id),
    UNIQUE KEY uk_sop_step_sequence (tenant_id, sop_id, version, sequence_no),
    KEY idx_sop_step_role (tenant_id, sop_id, version, role_required),
    KEY idx_sop_step_action (action_name),
    CONSTRAINT fk_sop_step_version
        FOREIGN KEY (tenant_id, sop_id, version)
        REFERENCES sop_versions(tenant_id, sop_id, version)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS sop_execution_states (
    tenant_id VARCHAR(64) NOT NULL,
    execution_id CHAR(36) NOT NULL,
    user_id VARCHAR(64) NOT NULL,
    conversation_id CHAR(36) NOT NULL,

    sop_id VARCHAR(64) NOT NULL,
    sop_version VARCHAR(32) NOT NULL,
    current_step_id VARCHAR(64) NOT NULL,

    execution_status ENUM(
        'active', 'waiting_input', 'waiting_confirmation',
        'completed', 'cancelled', 'failed'
    ) NOT NULL DEFAULT 'active',

    params_json JSON NOT NULL,
    completed_steps JSON NOT NULL,

    version_no INT UNSIGNED NOT NULL DEFAULT 1,
    started_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    completed_at DATETIME(6) NULL,

    PRIMARY KEY (tenant_id, execution_id),
    UNIQUE KEY uk_sop_active_conversation (tenant_id, conversation_id, sop_id, sop_version, execution_status),
    KEY idx_sop_execution_conversation (tenant_id, conversation_id, updated_at),
    KEY idx_sop_execution_tenant (tenant_id, execution_status),
    CONSTRAINT fk_sop_execution_conversation
        FOREIGN KEY (tenant_id, conversation_id)
        REFERENCES chat_conversations(tenant_id, conversation_id),
    CONSTRAINT fk_sop_execution_step
        FOREIGN KEY (tenant_id, sop_id, sop_version, current_step_id)
        REFERENCES sop_steps(tenant_id, sop_id, version, step_id),
    CONSTRAINT fk_sop_execution_user FOREIGN KEY (tenant_id, user_id)
        REFERENCES auth_users(tenant_id, user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ============================================================
-- 4. NL2SQL Schema Catalog
-- ============================================================

CREATE TABLE IF NOT EXISTS sql_data_domains (
    tenant_id VARCHAR(64) NOT NULL,
    domain_id VARCHAR(64) NOT NULL,

    domain_name VARCHAR(128) NOT NULL,
    description TEXT NOT NULL,
    status ENUM('active', 'disabled') NOT NULL DEFAULT 'active',

    default_time_column VARCHAR(128) NULL,
    max_rows INT UNSIGNED NOT NULL DEFAULT 1000,
    max_execution_seconds INT UNSIGNED NOT NULL DEFAULT 10,

    created_by VARCHAR(64) NOT NULL,
    updated_by VARCHAR(64) NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),

    PRIMARY KEY (tenant_id, domain_id),
    UNIQUE KEY uk_sql_domain_name (tenant_id, domain_name),
    KEY idx_sql_domain_status (tenant_id, status),
    CONSTRAINT fk_sql_domain_tenant FOREIGN KEY (tenant_id)
        REFERENCES auth_tenants(tenant_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS sql_allowed_tables (
    tenant_id VARCHAR(64) NOT NULL,
    domain_id VARCHAR(64) NOT NULL,
    table_name VARCHAR(128) NOT NULL,

    table_description TEXT NULL,
    required_tenant_filter BOOLEAN NOT NULL DEFAULT TRUE,
    allowed_joins JSON NULL,

    PRIMARY KEY (tenant_id, domain_id, table_name),
    CONSTRAINT fk_sql_table_domain
        FOREIGN KEY (tenant_id, domain_id)
        REFERENCES sql_data_domains(tenant_id, domain_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS sql_allowed_columns (
    tenant_id VARCHAR(64) NOT NULL,
    domain_id VARCHAR(64) NOT NULL,
    table_name VARCHAR(128) NOT NULL,
    column_name VARCHAR(128) NOT NULL,

    business_name VARCHAR(255) NOT NULL,
    data_type VARCHAR(64) NOT NULL,

    selectable BOOLEAN NOT NULL DEFAULT TRUE,
    filterable BOOLEAN NOT NULL DEFAULT TRUE,
    sortable BOOLEAN NOT NULL DEFAULT FALSE,
    aggregatable BOOLEAN NOT NULL DEFAULT FALSE,
    sensitive BOOLEAN NOT NULL DEFAULT FALSE,

    masking_rule VARCHAR(64) NULL,
    description TEXT NULL,

    PRIMARY KEY (tenant_id, domain_id, table_name, column_name),
    KEY idx_sql_column_sensitive (tenant_id, domain_id, sensitive),
    CONSTRAINT fk_sql_column_table
        FOREIGN KEY (tenant_id, domain_id, table_name)
        REFERENCES sql_allowed_tables(tenant_id, domain_id, table_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS sql_domain_permissions (
    tenant_id VARCHAR(64) NOT NULL,
    permission_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    domain_id VARCHAR(64) NOT NULL,

    subject_type ENUM('user', 'role', 'department') NOT NULL,
    subject_id VARCHAR(64) NOT NULL,

    row_predicate_template VARCHAR(2000) NOT NULL,
    allowed BOOLEAN NOT NULL DEFAULT TRUE,

    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),

    PRIMARY KEY (permission_id),
    UNIQUE KEY uk_sql_permission_subject (tenant_id, domain_id, subject_type, subject_id),
    KEY idx_sql_permission_subject_lookup (tenant_id, subject_type, subject_id, domain_id),
    CONSTRAINT fk_sql_permission_domain
        FOREIGN KEY (tenant_id, domain_id)
        REFERENCES sql_data_domains(tenant_id, domain_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ============================================================
-- 5. NL2SQL 审计
-- ============================================================

CREATE TABLE IF NOT EXISTS nl2sql_audit_logs (
    tenant_id VARCHAR(64) NOT NULL,
    audit_id CHAR(36) NOT NULL,
    user_id VARCHAR(64) NOT NULL,
    conversation_id CHAR(36) NULL,
    message_id BIGINT UNSIGNED NULL,
    trace_id VARCHAR(128) NULL,

    question TEXT NOT NULL,
    detected_domain VARCHAR(64) NULL,
    intent_confidence DECIMAL(5,4) NULL,

    generation_status ENUM('classified', 'generated', 'rejected', 'executed', 'failed') NOT NULL,

    generated_sql MEDIUMTEXT NULL,
    normalized_sql MEDIUMTEXT NULL,
    sql_hash CHAR(64) NULL,

    guard_status ENUM('not_checked', 'allowed', 'rejected') NOT NULL DEFAULT 'not_checked',
    guard_reason VARCHAR(500) NULL,

    execution_status ENUM(
        'not_executed', 'success', 'timeout', 'permission_denied', 'error'
    ) NOT NULL DEFAULT 'not_executed',

    query_id CHAR(36) NULL,
    row_count INT UNSIGNED NULL,
    duration_ms INT UNSIGNED NULL,

    error_code VARCHAR(64) NULL,
    error_message VARCHAR(1000) NULL,

    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    completed_at DATETIME(6) NULL,

    PRIMARY KEY (tenant_id, audit_id),
    KEY idx_nl2sql_audit_user_time (tenant_id, user_id, created_at),
    KEY idx_nl2sql_audit_domain_time (tenant_id, detected_domain, created_at),
    KEY idx_nl2sql_audit_status_time (execution_status, created_at),
    KEY idx_nl2sql_audit_query (query_id),
    KEY idx_nl2sql_audit_hash (sql_hash),
    CONSTRAINT fk_nl2sql_audit_message
        FOREIGN KEY (message_id)
        REFERENCES chat_messages(message_id),
    CONSTRAINT fk_nl2sql_audit_user FOREIGN KEY (tenant_id, user_id)
        REFERENCES auth_users(tenant_id, user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS nl2sql_result_samples (
    audit_id CHAR(36) NOT NULL,

    columns_json JSON NOT NULL,
    sample_rows_json JSON NULL,
    total_row_count INT UNSIGNED NOT NULL DEFAULT 0,
    truncated BOOLEAN NOT NULL DEFAULT FALSE,

    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),

    PRIMARY KEY (audit_id),
    CONSTRAINT fk_nl2sql_result_audit
        FOREIGN KEY (audit_id)
        REFERENCES nl2sql_audit_logs(audit_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ============================================================
-- 6. 工具调用（SOP 高风险动作 + 通用审计）
-- ============================================================

CREATE TABLE IF NOT EXISTS chat_tool_calls (
    tenant_id VARCHAR(64) NOT NULL,
    tool_call_id CHAR(36) NOT NULL,
    user_id VARCHAR(64) NOT NULL,
    conversation_id CHAR(36) NULL,
    message_id BIGINT UNSIGNED NULL,

    tool_name VARCHAR(128) NOT NULL,
    tool_version VARCHAR(32) NULL,
    arguments_json JSON NULL,

    risk_level ENUM('low', 'medium', 'high') NOT NULL DEFAULT 'low',
    authorization_status ENUM(
        'not_required', 'allowed', 'denied', 'pending_confirmation'
    ) NOT NULL,

    confirmation_message_id BIGINT UNSIGNED NULL,
    execution_status ENUM('not_executed', 'success', 'failed', 'cancelled') NOT NULL DEFAULT 'not_executed',

    result_summary JSON NULL,
    error_code VARCHAR(64) NULL,

    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    started_at DATETIME(6) NULL,
    completed_at DATETIME(6) NULL,

    PRIMARY KEY (tenant_id, tool_call_id),
    KEY idx_tool_call_user_time (tenant_id, user_id, created_at),
    KEY idx_tool_call_conversation (tenant_id, conversation_id, created_at),
    KEY idx_tool_call_risk_status (risk_level, execution_status),
    CONSTRAINT fk_tool_call_message
        FOREIGN KEY (message_id)
        REFERENCES chat_messages(message_id),
    CONSTRAINT fk_tool_call_user FOREIGN KEY (tenant_id, user_id)
        REFERENCES auth_users(tenant_id, user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ============================================================
-- 多轮会话结构化状态（第 4 步）
-- 供指代消解与能力续走使用；sop_execution_states 仍为 SOP 唯一状态源。
-- ============================================================

CREATE TABLE IF NOT EXISTS chat_session_states (
    tenant_id VARCHAR(64) NOT NULL,
    conversation_id CHAR(36) NOT NULL,
    user_id VARCHAR(64) NOT NULL,
    last_intent VARCHAR(32) NULL,
    last_domain VARCHAR(64) NULL,
    last_query_id CHAR(36) NULL,
    current_sop_id VARCHAR(64) NULL,
    current_sop_version VARCHAR(32) NULL,
    current_step_id VARCHAR(64) NULL,
    state_json JSON NOT NULL,
    version_no INT UNSIGNED NOT NULL DEFAULT 1,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (tenant_id, conversation_id),
    KEY idx_session_state_user (tenant_id, user_id, updated_at),
    CONSTRAINT fk_session_state_conv FOREIGN KEY (tenant_id, conversation_id)
        REFERENCES chat_conversations(tenant_id, conversation_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ============================================================
-- 7. Schema Registry（MVP）
-- ============================================================

CREATE TABLE IF NOT EXISTS sql_domain_keywords (
    tenant_id VARCHAR(64) NOT NULL,
    domain_id VARCHAR(64) NOT NULL,
    keyword VARCHAR(128) NOT NULL,
    weight DECIMAL(8,3) NOT NULL DEFAULT 1,
    PRIMARY KEY (tenant_id, domain_id, keyword),
    CONSTRAINT fk_sql_keyword_domain FOREIGN KEY (tenant_id, domain_id)
        REFERENCES sql_data_domains(tenant_id, domain_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT IGNORE INTO auth_permissions (permission_id, permission_code, description)
VALUES ('perm-schema-admin', 'schema:admin', '管理 NL2SQL Schema Registry');
