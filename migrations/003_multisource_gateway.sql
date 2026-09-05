-- ==========================================================
-- STEP 3D: MULTI-SOURCE JOB IMPORT GATEWAY MIGRATION
-- Adds source metadata, AI usage tracking, and observability
-- ==========================================================

-- 1. Add optional source metadata and AI tracking columns to raw_job_ingestions
ALTER TABLE raw_job_ingestions
ADD COLUMN IF NOT EXISTS source_url VARCHAR(500),
ADD COLUMN IF NOT EXISTS source_posted_date VARCHAR(50),
ADD COLUMN IF NOT EXISTS ai_used BOOLEAN DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS ai_skipped BOOLEAN DEFAULT TRUE,
ADD COLUMN IF NOT EXISTS ai_provider_name VARCHAR(50) DEFAULT 'local_deterministic';

-- 2. Indexes for source queries and analytics
CREATE INDEX IF NOT EXISTS idx_raw_ingest_source_type ON raw_job_ingestions(source_type);
CREATE INDEX IF NOT EXISTS idx_raw_ingest_ai_used ON raw_job_ingestions(ai_used);

-- 3. Idempotent check on job_sources raw_ingestion_id
CREATE INDEX IF NOT EXISTS idx_job_sources_raw_ingest ON job_sources(raw_ingestion_id);
