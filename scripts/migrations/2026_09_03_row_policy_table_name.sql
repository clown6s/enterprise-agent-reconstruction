-- ============================================================
-- Migration: scope row-level policies to a table.
-- ============================================================
-- sql_domain_permissions previously held one policy per (tenant, domain,
-- subject) with no notion of a specific table. Row-level policies must be
-- scoped to the table the generated SELECT reads, so add a table_name column
-- and fold it into the subject uniqueness key. For existing rows table_name
-- is NULL, which the catalog treats as "not applicable" (no policy applied),
-- preserving current behavior until rows are back-filled.
--
-- Apply with: mysql -u <user> -p <db> < this file
-- ============================================================

ALTER TABLE sql_domain_permissions
    DROP INDEX uk_sql_permission_subject,
    ADD COLUMN table_name VARCHAR(128) NULL AFTER subject_id,
    ADD UNIQUE KEY uk_sql_permission_subject
        (tenant_id, domain_id, table_name, subject_type, subject_id);
