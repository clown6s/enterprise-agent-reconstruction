-- Schema 元数据表外键级联删除迁移
-- 目的：
--   * 数据域生命周期内的子表，父表删除时自动级联清理，避免删除数据域时
--     残留孤儿行，也减少应用层按顺序手工 DELETE 的维护成本。
--   * 保留 `sql_data_domains -> auth_tenants` 的默认 RESTRICT：
--     删除租户不应连带删除该租户的全部 schema 元数据，应由独立的租户
--     注销流程处理。
--
-- 执行方式（需管理员账号，xxx 替换为库名）：
--   mysql -h <HOST> -P 3306 -u root -p <DB> < scripts/migrations/2026_09_04_schema_fk_cascade.sql
-- 或：
--   mysql -u root -p -e "USE <DB>; SOURCE scripts/migrations/2026_09_04_schema_fk_cascade.sql;"
--
-- 注意：本脚本假定外键名与 information_schema.KEY_COLUMN_USAGE 一致。
-- 若约定名与库中不同，ALTER TABLE 会失败；执行前可先核对各外键名。

-- 加到 sql_schema_versions 上：删除数据域时连带删除其全部版本快照
ALTER TABLE sql_schema_versions
  DROP FOREIGN KEY fk_schema_version_domain,
  ADD  CONSTRAINT fk_schema_version_domain
    FOREIGN KEY (tenant_id, domain_id) REFERENCES sql_data_domains (tenant_id, domain_id)
    ON DELETE CASCADE;

-- sql_allowed_joins 依赖 sql_schema_versions，级联跟随版本删除
ALTER TABLE sql_allowed_joins
  DROP FOREIGN KEY fk_schema_join_version,
  ADD  CONSTRAINT fk_schema_join_version
    FOREIGN KEY (tenant_id, version_id) REFERENCES sql_schema_versions (tenant_id, version_id)
    ON DELETE CASCADE;

-- sql_schema_change_logs 依赖 sql_schema_versions，级联跟随版本删除
ALTER TABLE sql_schema_change_logs
  DROP FOREIGN KEY fk_schema_change_version,
  ADD  CONSTRAINT fk_schema_change_version
    FOREIGN KEY (tenant_id, version_id) REFERENCES sql_schema_versions (tenant_id, version_id)
    ON DELETE CASCADE;

-- 加到 sql_allowed_tables 上：删除数据域时连带删除域下所有表登记
ALTER TABLE sql_allowed_tables
  DROP FOREIGN KEY fk_sql_table_domain,
  ADD  CONSTRAINT fk_sql_table_domain
    FOREIGN KEY (tenant_id, domain_id) REFERENCES sql_data_domains (tenant_id, domain_id)
    ON DELETE CASCADE;

-- sql_allowed_columns 依赖 sql_allowed_tables，级联跟随表登记删除
ALTER TABLE sql_allowed_columns
  DROP FOREIGN KEY fk_sql_column_table,
  ADD  CONSTRAINT fk_sql_column_table
    FOREIGN KEY (tenant_id, domain_id, table_name) REFERENCES sql_allowed_tables (tenant_id, domain_id, table_name)
    ON DELETE CASCADE;

-- sql_domain_keywords 依赖 sql_data_domains
ALTER TABLE sql_domain_keywords
  DROP FOREIGN KEY fk_sql_domain_keyword_domain,
  ADD  CONSTRAINT fk_sql_domain_keyword_domain
    FOREIGN KEY (tenant_id, domain_id) REFERENCES sql_data_domains (tenant_id, domain_id)
    ON DELETE CASCADE;

-- sql_domain_permissions 依赖 sql_data_domains
ALTER TABLE sql_domain_permissions
  DROP FOREIGN KEY fk_sql_permission_domain,
  ADD  CONSTRAINT fk_sql_permission_domain
    FOREIGN KEY (tenant_id, domain_id) REFERENCES sql_data_domains (tenant_id, domain_id)
    ON DELETE CASCADE;

-- 注意：sql_data_domains -> auth_tenants 的外键（fk_sql_domain_tenant）**故意不设 CASCADE**，
-- 保持默认 RESTRICT，防止删除租户时连带删除其全部 schema 配置。