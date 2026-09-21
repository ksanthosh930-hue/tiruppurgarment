-- 009_employer_job_posting_foundation.sql
-- Non-destructive idempotent database migration for Phase 2 (Employer Job Posting, Ownership & Moderation Foundation)
-- Datatype-safe: Integer foreign keys referencing public_users(id) and company_profiles(id)

-- 1. Add employer ownership and moderation columns to jobs table
ALTER TABLE jobs 
    ADD COLUMN IF NOT EXISTS employer_user_id INTEGER REFERENCES public_users(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS company_profile_id INTEGER REFERENCES company_profiles(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS rejection_reason TEXT;

-- 2. Indexes for fast employer dashboard queries & moderation filtering
CREATE INDEX IF NOT EXISTS idx_jobs_employer_user_id ON jobs(employer_user_id);
CREATE INDEX IF NOT EXISTS idx_jobs_company_profile_id ON jobs(company_profile_id);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_published_at ON jobs(published_at);
