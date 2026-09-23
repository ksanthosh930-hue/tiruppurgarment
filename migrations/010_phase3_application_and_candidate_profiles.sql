-- 010_phase3_application_and_candidate_profiles.sql
-- Non-destructive idempotent database migration for Phase 3
-- Preserves existing tables, historical application records (id=16), and legacy foreign keys.

-- 1. Enhance individual_profiles with education, preference, and location fields (no default values)
ALTER TABLE individual_profiles
    ADD COLUMN IF NOT EXISTS department VARCHAR(100),
    ADD COLUMN IF NOT EXISTS preferred_job_role VARCHAR(100),
    ADD COLUMN IF NOT EXISTS preferred_department VARCHAR(100),
    ADD COLUMN IF NOT EXISTS preferred_location VARCHAR(255),
    ADD COLUMN IF NOT EXISTS qualification VARCHAR(100),
    ADD COLUMN IF NOT EXISTS course VARCHAR(150),
    ADD COLUMN IF NOT EXISTS institution VARCHAR(255),
    ADD COLUMN IF NOT EXISTS passing_year VARCHAR(10),
    ADD COLUMN IF NOT EXISTS city VARCHAR(100),
    ADD COLUMN IF NOT EXISTS district VARCHAR(100);

-- 2. Evolve existing job_applications table with active public_users relationships
ALTER TABLE job_applications
    ADD COLUMN IF NOT EXISTS candidate_user_id INTEGER REFERENCES public_users(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS individual_profile_id INTEGER REFERENCES individual_profiles(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS cover_message TEXT;

-- 3. Partial unique index to protect against duplicate candidate applications (ignores legacy NULL candidate_user_id)
CREATE UNIQUE INDEX IF NOT EXISTS idx_job_app_unique_candidate 
    ON job_applications(job_id, candidate_user_id) 
    WHERE candidate_user_id IS NOT NULL;

-- 4. High-performance lookup indexes for applications
CREATE INDEX IF NOT EXISTS idx_job_app_candidate_user ON job_applications(candidate_user_id);
CREATE INDEX IF NOT EXISTS idx_job_app_individual_profile ON job_applications(individual_profile_id);
CREATE INDEX IF NOT EXISTS idx_job_app_status ON job_applications(status);
