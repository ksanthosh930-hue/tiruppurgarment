-- ==========================================================
-- STEP 3D.5: JOB OPENINGS & MULTI-VACANCY MIGRATION
-- Non-destructive schema addition for vacancy counts and walk-in details
-- ==========================================================

-- 1. Add openings_count and walk-in columns to jobs table
ALTER TABLE jobs
ADD COLUMN IF NOT EXISTS openings_count INTEGER NOT NULL DEFAULT 1,
ADD COLUMN IF NOT EXISTS walk_in_start_date DATE,
ADD COLUMN IF NOT EXISTS walk_in_end_date DATE,
ADD COLUMN IF NOT EXISTS interview_time VARCHAR(100),
ADD COLUMN IF NOT EXISTS immediate_joiners BOOLEAN DEFAULT FALSE;

-- Ensure positive openings count constraint safely
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'chk_jobs_openings_count_positive'
    ) THEN
        ALTER TABLE jobs ADD CONSTRAINT chk_jobs_openings_count_positive CHECK (openings_count >= 1);
    END IF;
END $$;

-- 2. Add openings_count and walk-in details to raw_job_ingestions
ALTER TABLE raw_job_ingestions
ADD COLUMN IF NOT EXISTS openings_count INTEGER DEFAULT 1,
ADD COLUMN IF NOT EXISTS walk_in_start_date DATE,
ADD COLUMN IF NOT EXISTS walk_in_end_date DATE,
ADD COLUMN IF NOT EXISTS interview_time VARCHAR(100),
ADD COLUMN IF NOT EXISTS immediate_joiners BOOLEAN DEFAULT FALSE;

-- 3. Indexes for fast filtering
CREATE INDEX IF NOT EXISTS idx_jobs_openings_count ON jobs(openings_count);
