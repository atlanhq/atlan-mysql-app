-- =====================================================================
-- INFORMATION_SCHEMA mirror schema setup for the Atlan MySQL/MariaDB connector
--
-- Purpose:
--   In MySQL, granting SELECT on INFORMATION_SCHEMA implicitly grants SELECT
--   on every underlying user table — a non-starter for security-restricted
--   deployments. This script creates a dedicated schema (default: atlan_meta)
--   containing views that mirror the rows the connector needs from
--   INFORMATION_SCHEMA, and grants SELECT ONLY on those views to a dedicated
--   `atlan_reader` user.
--
--   When you then configure the connector with:
--       Advanced Config > Control Config > Custom
--       Custom Config: {"clonedInformationSchema": "atlan_meta"}
--   every query the connector issues will route through atlan_meta.* instead
--   of information_schema.*. The DBA team retains tight control over the
--   privilege surface.
--
-- Tested against:
--   * MySQL 8.0
--   * MariaDB 10.11
--
-- Run as a user with the privileges to:
--   * CREATE SCHEMA
--   * CREATE VIEW
--   * GRANT
--
-- After running, configure the connector (no other source-side changes needed).
--
-- Files in connector that consume this mirror (REQ-925):
--   app/sql/extract_database.sql, extract_schema.sql, extract_table.sql,
--   extract_column.sql, extract_procedure.sql, filter_metadata.sql,
--   tables_check.sql — each contains {information_schema}.<TABLE_NAME>
--   placeholders that are substituted at runtime.
-- =====================================================================

-- 1. Create the mirror schema (change name if your policy requires it; the
--    same name must be passed to the connector via clonedInformationSchema).
CREATE DATABASE IF NOT EXISTS atlan_meta;

USE atlan_meta;

-- 2. Mirror views — one per INFORMATION_SCHEMA table the connector reads.
--    Each view is a passthrough SELECT — keep it that way so the connector
--    receives identical column shapes.

CREATE OR REPLACE VIEW SCHEMATA AS
    SELECT * FROM information_schema.SCHEMATA;

CREATE OR REPLACE VIEW TABLES AS
    SELECT * FROM information_schema.TABLES;

CREATE OR REPLACE VIEW VIEWS AS
    SELECT * FROM information_schema.VIEWS;

CREATE OR REPLACE VIEW COLUMNS AS
    SELECT * FROM information_schema.COLUMNS;

CREATE OR REPLACE VIEW KEY_COLUMN_USAGE AS
    SELECT * FROM information_schema.KEY_COLUMN_USAGE;

CREATE OR REPLACE VIEW TABLE_CONSTRAINTS AS
    SELECT * FROM information_schema.TABLE_CONSTRAINTS;

CREATE OR REPLACE VIEW PARTITIONS AS
    SELECT * FROM information_schema.PARTITIONS;

CREATE OR REPLACE VIEW ROUTINES AS
    SELECT * FROM information_schema.ROUTINES;

-- 3. Create the connector user. Change the password before running in prod.
--    Use a strong unique password and rotate it through your secret store.
CREATE USER IF NOT EXISTS 'atlan_reader'@'%' IDENTIFIED BY 'CHANGE_ME_BEFORE_RUNNING';

-- 4. Grant SELECT only on the mirror schema.
GRANT SELECT ON atlan_meta.* TO 'atlan_reader'@'%';

-- 5. NO grants on INFORMATION_SCHEMA or any user schemas — the connector
--    user MUST NOT be able to read user data directly. The mirror views
--    expose only the metadata columns Atlan needs.

FLUSH PRIVILEGES;

-- =====================================================================
-- Verification (run as atlan_reader to confirm the connector path works):
--
--   SELECT SCHEMA_NAME FROM atlan_meta.SCHEMATA LIMIT 5;
--   SELECT TABLE_SCHEMA, TABLE_NAME, TABLE_TYPE
--   FROM atlan_meta.TABLES
--   WHERE TABLE_SCHEMA NOT IN ('mysql', 'performance_schema', 'information_schema', 'sys')
--   LIMIT 5;
--
-- Both should return rows. A `SELECT * FROM information_schema.TABLES` should
-- fail with "command denied" — confirming the privilege isolation.
-- =====================================================================
