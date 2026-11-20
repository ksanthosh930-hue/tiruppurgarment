-- ==============================================================================
-- 015_google_sub_unique_index.sql
-- Standalone, Zero-Downtime Concurrent Partial Unique Index on google_sub
-- Target Table: public_users
-- ==============================================================================
--
-- EXECUTION RULES:
-- 1. DO NOT WRAP THIS SCRIPT IN A TRANSACTION (NO BEGIN / COMMIT).
--    PostgreSQL prohibits CREATE INDEX CONCURRENTLY inside a transaction block.
-- 2. Execute via psql with autocommit enabled or in the Supabase SQL Editor.
-- 3. Run Pre-Check queries first. If any duplicate is found, STOP and investigate.
--    This script WILL NOT silently delete or alter any user record.
-- ==============================================================================

-- ------------------------------------------------------------------------------
-- STEP 1: PRE-CHECK – Diagnostic Query to Detect Non-Null google_sub Duplicates
-- ------------------------------------------------------------------------------
-- If this query returns ANY rows, DO NOT proceed. Investigate the accounts manually.
SELECT 
    google_sub, 
    COUNT(*) AS duplicate_count, 
    array_agg(id ORDER BY id ASC) AS user_ids, 
    array_agg(email ORDER BY id ASC) AS emails
FROM public_users
WHERE google_sub IS NOT NULL
GROUP BY google_sub
HAVING COUNT(*) > 1;

-- ------------------------------------------------------------------------------
-- STEP 2: PRE-CHECK ASSERTION – Automated Guard
-- ------------------------------------------------------------------------------
-- Aborts execution with an explicit error if any duplicate non-null google_sub exists.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM public_users
        WHERE google_sub IS NOT NULL
        GROUP BY google_sub
        HAVING COUNT(*) > 1
    ) THEN
        RAISE EXCEPTION 'PRE-CHECK FAILED: Found duplicate google_sub value(s) in public_users. Index creation aborted. Resolve duplicates manually without data loss.';
    ELSE
        RAISE NOTICE 'PRE-CHECK PASSED: Zero duplicate google_sub values found. Safe to create unique index.';
    END IF;
END $$;

-- ------------------------------------------------------------------------------
-- STEP 3: CONCURRENT PARTIAL UNIQUE INDEX CREATION
-- ------------------------------------------------------------------------------
-- CONCURRENTLY builds the index without acquiring an exclusive table lock on public_users,
-- ensuring zero downtime for active job seekers, employers, and visitors.
-- Partial filter (WHERE google_sub IS NOT NULL) permits multiple local users with NULL google_sub.
CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS idx_public_users_google_sub
    ON public_users (google_sub)
    WHERE google_sub IS NOT NULL;

-- ------------------------------------------------------------------------------
-- STEP 4: POST-CREATION VERIFICATION
-- ------------------------------------------------------------------------------
-- Verify index existence, uniqueness flag (indisunique = true), and validity (indisvalid = true).
-- Note: An invalid index (indisvalid = false) occurs only if the concurrent build failed,
-- in which case it should be dropped (DROP INDEX CONCURRENTLY) and re-run.
SELECT 
    c.relname AS table_name,
    i.relname AS index_name,
    idx.indisunique AS is_unique,
    idx.indisvalid AS is_valid,
    pg_get_indexdef(idx.indexrelid) AS index_definition
FROM pg_index idx
JOIN pg_class i ON i.oid = idx.indexrelid
JOIN pg_class c ON c.oid = idx.indrelid
WHERE c.relname = 'public_users'
  AND i.relname = 'idx_public_users_google_sub';
