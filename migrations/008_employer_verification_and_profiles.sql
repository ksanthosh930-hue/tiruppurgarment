-- 008_employer_verification_and_profiles.sql
-- Non-destructive idempotent database migration for Employer Verification and Profile Foundation (Phase 1)
-- Preserves existing tables, existing users, and existing constraints.

-- 1. Add whatsapp, area, and verification_status to company_profiles
ALTER TABLE company_profiles 
    ADD COLUMN IF NOT EXISTS whatsapp VARCHAR(50),
    ADD COLUMN IF NOT EXISTS area VARCHAR(255),
    ADD COLUMN IF NOT EXISTS verification_status VARCHAR(50) DEFAULT 'pending';

-- 2. Safe check constraint for verification_status (pending, verified, rejected, suspended)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'company_profiles_verification_status_check'
    ) THEN
        ALTER TABLE company_profiles
            ADD CONSTRAINT company_profiles_verification_status_check
            CHECK (verification_status IN ('pending', 'verified', 'rejected', 'suspended'));
    END IF;
END $$;

-- 3. Set default for any existing company profiles with NULL verification_status
UPDATE company_profiles 
SET verification_status = 'pending' 
WHERE verification_status IS NULL;

-- 4. Create index on verification_status for future moderation queries
CREATE INDEX IF NOT EXISTS idx_company_profiles_verification_status ON company_profiles(verification_status);
CREATE INDEX IF NOT EXISTS idx_company_profiles_whatsapp ON company_profiles(whatsapp);
CREATE INDEX IF NOT EXISTS idx_company_profiles_area ON company_profiles(area);
