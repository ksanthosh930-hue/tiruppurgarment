-- ==========================================================
-- STEP 3F: WEBSITE JOB SOURCE CONNECTORS MIGRATION
-- Source Configuration, Health Status, Rate Limits, and Crawl Logs
-- ==========================================================

-- 1. Create website_sources configuration and health table
CREATE TABLE IF NOT EXISTS website_sources (
    id SERIAL PRIMARY KEY,
    source_id VARCHAR(50) UNIQUE NOT NULL,
    source_name VARCHAR(100) NOT NULL,
    source_type VARCHAR(50) NOT NULL DEFAULT 'website',
    base_url VARCHAR(255) NOT NULL,
    enabled BOOLEAN DEFAULT TRUE,
    crawl_allowed BOOLEAN DEFAULT TRUE,
    status VARCHAR(50) NOT NULL DEFAULT 'ACTIVE', -- ACTIVE, DISABLED, BLOCKED_BY_ROBOTS, BLOCKED_BY_POLICY, ERROR, NOT_CONFIGURED
    schedule_enabled BOOLEAN DEFAULT FALSE,
    crawl_interval_minutes INTEGER DEFAULT 60,
    requests_per_minute INTEGER DEFAULT 20,
    last_crawled_at TIMESTAMP,
    last_success_at TIMESTAMP,
    last_error_at TIMESTAMP,
    last_error_message TEXT,
    total_discovered INTEGER DEFAULT 0,
    total_imported INTEGER DEFAULT 0,
    total_duplicates INTEGER DEFAULT 0,
    total_errors INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. Create crawl_run_logs table for auditability and observability
CREATE TABLE IF NOT EXISTS crawl_run_logs (
    id SERIAL PRIMARY KEY,
    source_id VARCHAR(50) REFERENCES website_sources(source_id) ON DELETE CASCADE,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    duration_seconds NUMERIC(8,2),
    pages_visited INTEGER DEFAULT 0,
    job_urls_discovered INTEGER DEFAULT 0,
    new_imported INTEGER DEFAULT 0,
    exact_duplicates INTEGER DEFAULT 0,
    possible_duplicates INTEGER DEFAULT 0,
    extraction_successes INTEGER DEFAULT 0,
    extraction_failures INTEGER DEFAULT 0,
    errors_count INTEGER DEFAULT 0,
    status VARCHAR(50) DEFAULT 'COMPLETED', -- COMPLETED, FAILED, BLOCKED
    log_summary JSONB,
    error_details TEXT
);

-- 3. Indexes for queries and analytics
CREATE INDEX IF NOT EXISTS idx_website_sources_status ON website_sources(status);
CREATE INDEX IF NOT EXISTS idx_website_sources_enabled ON website_sources(enabled);
CREATE INDEX IF NOT EXISTS idx_crawl_run_logs_source ON crawl_run_logs(source_id);
CREATE INDEX IF NOT EXISTS idx_crawl_run_logs_started ON crawl_run_logs(started_at DESC);

-- 4. Seed initial approved website sources idempotently
INSERT INTO website_sources (source_id, source_name, source_type, base_url, enabled, crawl_allowed, status)
VALUES 
    ('sankar_jobs', 'Sankar Jobs', 'website', 'https://sankarjobs.com', TRUE, TRUE, 'ACTIVE'),
    ('cotton_jobs', 'Cotton Jobs', 'website', 'https://cottonjobs.in', TRUE, TRUE, 'ACTIVE')
ON CONFLICT (source_id) DO UPDATE 
SET source_name = EXCLUDED.source_name,
    base_url = EXCLUDED.base_url;
