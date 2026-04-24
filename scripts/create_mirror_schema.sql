-- =============================================================
-- Atlan MySQL Connector: Mirror Schema Setup Script
-- =============================================================
-- Purpose: Create a mirror schema for INFORMATION_SCHEMA tables
--          when direct INFORMATION_SCHEMA access is restricted.
--
-- Usage:   Replace 'atlan_meta' with your desired schema name.
--          Replace 'atlan_user' with the Atlan service account.
--
-- Note:    MySQL views on INFORMATION_SCHEMA provide live data —
--          no refresh/cron needed (unlike Redshift's table-copy approach).
--          The executing user must have SELECT on INFORMATION_SCHEMA.
-- =============================================================

-- 1. Create mirror schema
CREATE SCHEMA IF NOT EXISTS atlan_meta;

-- 2. Create views mirroring required INFORMATION_SCHEMA tables
CREATE OR REPLACE VIEW atlan_meta.SCHEMATA AS
    SELECT * FROM information_schema.SCHEMATA;

CREATE OR REPLACE VIEW atlan_meta.TABLES AS
    SELECT * FROM information_schema.TABLES;

CREATE OR REPLACE VIEW atlan_meta.COLUMNS AS
    SELECT * FROM information_schema.COLUMNS;

CREATE OR REPLACE VIEW atlan_meta.VIEWS AS
    SELECT * FROM information_schema.VIEWS;

CREATE OR REPLACE VIEW atlan_meta.PARTITIONS AS
    SELECT * FROM information_schema.PARTITIONS;

CREATE OR REPLACE VIEW atlan_meta.ROUTINES AS
    SELECT * FROM information_schema.ROUTINES;

CREATE OR REPLACE VIEW atlan_meta.KEY_COLUMN_USAGE AS
    SELECT * FROM information_schema.KEY_COLUMN_USAGE;

CREATE OR REPLACE VIEW atlan_meta.TABLE_CONSTRAINTS AS
    SELECT * FROM information_schema.TABLE_CONSTRAINTS;

-- 3. Grant SELECT on mirror schema to Atlan service account
GRANT SELECT ON atlan_meta.* TO 'atlan_user'@'%';

-- 4. Verify setup
SELECT TABLE_SCHEMA, TABLE_NAME, TABLE_TYPE
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = 'atlan_meta'
ORDER BY TABLE_NAME;
