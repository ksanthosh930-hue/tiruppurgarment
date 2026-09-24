-- 011_phase4_saved_jobs.sql
-- Non-destructive idempotent database migration for Phase 4A (Saved Jobs Backend)
-- Preserves existing tables, historical application records (id=16), and legacy foreign keys.

-- 1. Create saved_jobs table for employee bookmarking
CREATE TABLE IF NOT EXISTS saved_jobs (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES public_users(id) ON DELETE CASCADE,
    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_saved_jobs_user_job UNIQUE (user_id, job_id)
);

-- 2. Performance indexes for saved jobs lookups
CREATE INDEX IF NOT EXISTS idx_saved_jobs_user_id ON saved_jobs(user_id);
CREATE INDEX IF NOT EXISTS idx_saved_jobs_job_id ON saved_jobs(job_id);
CREATE INDEX IF NOT EXISTS idx_saved_jobs_created_at ON saved_jobs(created_at DESC);
