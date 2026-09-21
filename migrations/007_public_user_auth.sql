-- 007_public_user_auth.sql
-- Non-destructive idempotent database migration for Public User Authentication System (Step 7)
-- Completely isolated from existing Admin/CMS authentication tables (users, admins, cms_admin_sessions)

-- 1. Public Users Table (Pure authentication / account identity)
CREATE TABLE IF NOT EXISTS public_users (
    id SERIAL PRIMARY KEY,
    account_type VARCHAR(50) NOT NULL CHECK (account_type IN ('individual', 'company')),
    email VARCHAR(255) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    email_verified BOOLEAN DEFAULT FALSE,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_public_users_email ON public_users(email);
CREATE INDEX IF NOT EXISTS idx_public_users_account_type ON public_users(account_type);

-- 2. Email OTP Verifications Table
CREATE TABLE IF NOT EXISTS email_otp_verifications (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) NOT NULL,
    otp_hash VARCHAR(255) NOT NULL,
    purpose VARCHAR(50) NOT NULL DEFAULT 'registration',
    expires_at TIMESTAMP NOT NULL,
    attempts INTEGER DEFAULT 0,
    verified_at TIMESTAMP,
    token_nonce VARCHAR(64),
    is_consumed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_email_otp_email_purpose ON email_otp_verifications(email, purpose);
CREATE INDEX IF NOT EXISTS idx_email_otp_expires_at ON email_otp_verifications(expires_at);
CREATE INDEX IF NOT EXISTS idx_email_otp_token_nonce ON email_otp_verifications(token_nonce);

-- 3. Public User Sessions Table (Completely separate from cms_admin_sessions)
CREATE TABLE IF NOT EXISTS public_user_sessions (
    id SERIAL PRIMARY KEY,
    token VARCHAR(255) NOT NULL UNIQUE,
    user_id INTEGER NOT NULL REFERENCES public_users(id) ON DELETE CASCADE,
    expires_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_public_user_sessions_token ON public_user_sessions(token);
CREATE INDEX IF NOT EXISTS idx_public_user_sessions_user_id ON public_user_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_public_user_sessions_expires_at ON public_user_sessions(expires_at);

-- 4. Individual / Job Seeker Profiles Table
CREATE TABLE IF NOT EXISTS individual_profiles (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL UNIQUE REFERENCES public_users(id) ON DELETE CASCADE,
    full_name VARCHAR(255) NOT NULL,
    email VARCHAR(255),
    mobile VARCHAR(50),
    location VARCHAR(255),
    job_title VARCHAR(255),
    experience_years NUMERIC(4,1) DEFAULT 0,
    skills TEXT,
    expected_salary VARCHAR(100),
    resume_url VARCHAR(255),
    profile_photo_url VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_individual_profiles_user_id ON individual_profiles(user_id);
CREATE INDEX IF NOT EXISTS idx_individual_profiles_mobile ON individual_profiles(mobile);
CREATE INDEX IF NOT EXISTS idx_individual_profiles_location ON individual_profiles(location);

-- 5. Company / Employer Profiles Table
CREATE TABLE IF NOT EXISTS company_profiles (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL UNIQUE REFERENCES public_users(id) ON DELETE CASCADE,
    company_name VARCHAR(255) NOT NULL,
    contact_person VARCHAR(255),
    email VARCHAR(255),
    mobile VARCHAR(50),
    business_type VARCHAR(100),
    location VARCHAR(255),
    address TEXT,
    website VARCHAR(255),
    company_description TEXT,
    company_logo VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_company_profiles_user_id ON company_profiles(user_id);
CREATE INDEX IF NOT EXISTS idx_company_profiles_name ON company_profiles(company_name);
