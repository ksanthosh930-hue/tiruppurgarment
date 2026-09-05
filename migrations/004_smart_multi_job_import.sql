-- ==========================================================
-- STEP 3D.5: SMART MULTI-JOB IMPORT GATEWAY MIGRATION
-- Adds parent ingestion linkage, vacancy indexes, and multi-job tracking
-- ==========================================================

-- 1. Add multi-job columns to raw_job_ingestions
ALTER TABLE raw_job_ingestions
ADD COLUMN IF NOT EXISTS parent_ingestion_id INTEGER REFERENCES raw_job_ingestions(id) ON DELETE CASCADE,
ADD COLUMN IF NOT EXISTS vacancy_index INTEGER DEFAULT 1,
ADD COLUMN IF NOT EXISTS total_vacancies INTEGER DEFAULT 1;

-- 2. Indexes for multi-job lookup and hierarchy queries
CREATE INDEX IF NOT EXISTS idx_raw_ingest_parent_id ON raw_job_ingestions(parent_ingestion_id);
CREATE INDEX IF NOT EXISTS idx_raw_ingest_vacancy_index ON raw_job_ingestions(vacancy_index);
