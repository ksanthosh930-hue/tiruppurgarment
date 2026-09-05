-- 002_job_ingestion.sql
-- Step 3B: Job Ingestion Staging, AI Extraction, and Multi-Source Traceability

-- 1. Create raw_job_ingestions staging table
CREATE TABLE IF NOT EXISTS raw_job_ingestions (
    id SERIAL PRIMARY KEY,
    source_type VARCHAR(50) NOT NULL DEFAULT 'poster_upload',
    source_name VARCHAR(255),
    source_reference VARCHAR(255),
    raw_text TEXT,
    raw_image_path VARCHAR(255),
    content_hash VARCHAR(64),
    media_hash VARCHAR(64),
    status VARCHAR(50) NOT NULL DEFAULT 'INGESTED',
    extracted_data JSONB,
    raw_ai_response JSONB,
    confidence_score NUMERIC(4,3),
    duplicate_score NUMERIC(4,3),
    matched_job_id INTEGER REFERENCES jobs(id) ON DELETE SET NULL,
    matched_company_id INTEGER REFERENCES companies(id) ON DELETE SET NULL,
    duplicate_reasons JSONB,
    extraction_warnings JSONB,
    error_log TEXT,
    retry_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    processed_at TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. Performance indexes for queue queries and hash lookups
CREATE INDEX IF NOT EXISTS idx_raw_ingest_status ON raw_job_ingestions(status);
CREATE INDEX IF NOT EXISTS idx_raw_ingest_content_hash ON raw_job_ingestions(content_hash);
CREATE INDEX IF NOT EXISTS idx_raw_ingest_media_hash ON raw_job_ingestions(media_hash);
CREATE INDEX IF NOT EXISTS idx_raw_ingest_created_at ON raw_job_ingestions(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_raw_ingest_matched_job ON raw_job_ingestions(matched_job_id);
CREATE INDEX IF NOT EXISTS idx_raw_ingest_matched_comp ON raw_job_ingestions(matched_company_id);

-- 3. Ensure job_sources table has raw_ingestion_id reference if not present
ALTER TABLE job_sources ADD COLUMN IF NOT EXISTS raw_ingestion_id INTEGER REFERENCES raw_job_ingestions(id) ON DELETE SET NULL;
