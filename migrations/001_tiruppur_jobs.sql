-- 001_tiruppur_jobs.sql
-- Non-destructive idempotent database migration for Tiruppur Jobs Foundation (Step 2)

-- 1. Ensure companies table and columns
CREATE TABLE IF NOT EXISTS companies (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    slug VARCHAR(255) NOT NULL UNIQUE,
    logo_url VARCHAR(255),
    description TEXT,
    location VARCHAR(255),
    website VARCHAR(255),
    contact_email VARCHAR(255),
    contact_phone VARCHAR(50),
    is_verified BOOLEAN DEFAULT FALSE,
    status VARCHAR(50) NOT NULL DEFAULT 'ACTIVE',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE companies ADD COLUMN IF NOT EXISTS logo_url VARCHAR(255);
ALTER TABLE companies ADD COLUMN IF NOT EXISTS location VARCHAR(255);
ALTER TABLE companies ADD COLUMN IF NOT EXISTS contact_email VARCHAR(255);
ALTER TABLE companies ADD COLUMN IF NOT EXISTS contact_phone VARCHAR(50);
ALTER TABLE companies ADD COLUMN IF NOT EXISTS is_verified BOOLEAN DEFAULT FALSE;
ALTER TABLE companies ADD COLUMN IF NOT EXISTS status VARCHAR(50) DEFAULT 'ACTIVE';
ALTER TABLE companies ALTER COLUMN created_at SET DEFAULT CURRENT_TIMESTAMP;
ALTER TABLE companies ALTER COLUMN updated_at SET DEFAULT CURRENT_TIMESTAMP;
ALTER TABLE companies ALTER COLUMN description DROP NOT NULL;

-- 2. Ensure jobs table and columns
CREATE TABLE IF NOT EXISTS jobs (
    id SERIAL PRIMARY KEY,
    company_id INTEGER REFERENCES companies(id) ON DELETE SET NULL,
    title VARCHAR(255) NOT NULL,
    slug VARCHAR(255) NOT NULL UNIQUE,
    department VARCHAR(100) NOT NULL,
    job_role VARCHAR(100) NOT NULL,
    job_type VARCHAR(50) NOT NULL DEFAULT 'Full Time',
    location VARCHAR(255) NOT NULL,
    experience_min INTEGER DEFAULT 0,
    experience_max INTEGER,
    salary_min NUMERIC(10,2),
    salary_max NUMERIC(10,2),
    salary_text VARCHAR(100),
    description TEXT NOT NULL,
    requirements TEXT,
    skills TEXT,
    qualification VARCHAR(255),
    gender VARCHAR(50),
    contact_phone VARCHAR(50),
    contact_whatsapp VARCHAR(50),
    contact_email VARCHAR(255),
    application_url VARCHAR(255),
    source_type VARCHAR(50) DEFAULT 'manual',
    source_name VARCHAR(255),
    source_url VARCHAR(255),
    source_posted_at TIMESTAMP,
    poster_image_url VARCHAR(255),
    status VARCHAR(50) NOT NULL DEFAULT 'draft',
    is_featured BOOLEAN DEFAULT FALSE,
    is_archived BOOLEAN DEFAULT FALSE,
    verification_status VARCHAR(50) NOT NULL DEFAULT 'unverified',
    published_at TIMESTAMP,
    expires_at TIMESTAMP,
    duplicate_group_id VARCHAR(100),
    duplicate_of_job_id INTEGER REFERENCES jobs(id) ON DELETE SET NULL,
    source_hash VARCHAR(64),
    content_hash VARCHAR(64),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE jobs ADD COLUMN IF NOT EXISTS department VARCHAR(100);
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS job_role VARCHAR(100);
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS job_type VARCHAR(50) DEFAULT 'Full Time';
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS location VARCHAR(255);
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS experience_min INTEGER DEFAULT 0;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS experience_max INTEGER;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS salary_min NUMERIC(10,2);
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS salary_max NUMERIC(10,2);
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS salary_text VARCHAR(100);
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS requirements TEXT;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS skills TEXT;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS qualification VARCHAR(255);
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS gender VARCHAR(50);
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS contact_phone VARCHAR(50);
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS contact_whatsapp VARCHAR(50);
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS contact_email VARCHAR(255);
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS application_url VARCHAR(255);
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS source_type VARCHAR(50) DEFAULT 'manual';
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS source_name VARCHAR(255);
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS source_url VARCHAR(255);
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS source_posted_at TIMESTAMP;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS poster_image_url VARCHAR(255);
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS status VARCHAR(50) DEFAULT 'draft';
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS is_featured BOOLEAN DEFAULT FALSE;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS is_archived BOOLEAN DEFAULT FALSE;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS verification_status VARCHAR(50) DEFAULT 'unverified';
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS published_at TIMESTAMP;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS duplicate_group_id VARCHAR(100);
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS duplicate_of_job_id INTEGER REFERENCES jobs(id) ON DELETE SET NULL;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS source_hash VARCHAR(64);
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS content_hash VARCHAR(64);
ALTER TABLE jobs ALTER COLUMN created_at SET DEFAULT CURRENT_TIMESTAMP;
ALTER TABLE jobs ALTER COLUMN updated_at SET DEFAULT CURRENT_TIMESTAMP;
ALTER TABLE jobs ALTER COLUMN company_id DROP NOT NULL;

-- 3. Create job_sources table
CREATE TABLE IF NOT EXISTS job_sources (
    id SERIAL PRIMARY KEY,
    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    source_type VARCHAR(50) NOT NULL DEFAULT 'manual',
    source_name VARCHAR(255),
    source_url VARCHAR(255),
    source_message_reference VARCHAR(255),
    source_posted_at TIMESTAMP,
    source_hash VARCHAR(64),
    raw_content_reference TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 4. Create job_seeker_profiles table
CREATE TABLE IF NOT EXISTS job_seeker_profiles (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    full_name VARCHAR(255) NOT NULL,
    mobile VARCHAR(50) NOT NULL,
    whatsapp_number VARCHAR(50),
    location VARCHAR(255),
    department VARCHAR(100),
    job_role VARCHAR(100),
    experience_years NUMERIC(4,1) DEFAULT 0,
    skills TEXT,
    current_company VARCHAR(255),
    expected_salary VARCHAR(100),
    preferred_location VARCHAR(255),
    resume_url VARCHAR(255),
    profile_photo_url VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 5. Create job_applications table
CREATE TABLE IF NOT EXISTS job_applications (
    id SERIAL PRIMARY KEY,
    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    job_seeker_profile_id INTEGER REFERENCES job_seeker_profiles(id) ON DELETE SET NULL,
    applicant_name VARCHAR(255) NOT NULL,
    applicant_phone VARCHAR(50) NOT NULL,
    applicant_email VARCHAR(255),
    resume_url VARCHAR(255),
    cover_letter TEXT,
    status VARCHAR(50) NOT NULL DEFAULT 'applied',
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 6. High-Performance Indexes
CREATE INDEX IF NOT EXISTS idx_jobs_status_published ON jobs(status, published_at DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_department ON jobs(department);
CREATE INDEX IF NOT EXISTS idx_jobs_role ON jobs(job_role);
CREATE INDEX IF NOT EXISTS idx_jobs_location ON jobs(location);
CREATE INDEX IF NOT EXISTS idx_jobs_company_id ON jobs(company_id);
CREATE INDEX IF NOT EXISTS idx_jobs_featured ON jobs(is_featured);
CREATE INDEX IF NOT EXISTS idx_jobs_is_archived ON jobs(is_archived);
CREATE INDEX IF NOT EXISTS idx_companies_slug ON companies(slug);
CREATE INDEX IF NOT EXISTS idx_job_sources_job_id ON job_sources(job_id);
CREATE INDEX IF NOT EXISTS idx_job_seeker_mobile ON job_seeker_profiles(mobile);
CREATE INDEX IF NOT EXISTS idx_job_seeker_user ON job_seeker_profiles(user_id);
CREATE INDEX IF NOT EXISTS idx_job_app_job ON job_applications(job_id);
CREATE INDEX IF NOT EXISTS idx_job_app_user ON job_applications(user_id);
