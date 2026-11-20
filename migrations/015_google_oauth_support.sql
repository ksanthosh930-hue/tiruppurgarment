-- 015_google_oauth_support.sql
-- Production-Safe Additive Migration for Google Identity Support
-- Preserves existing password_hash NOT NULL constraint using Option B (unusable sentinel hashes)

-- 1. Add google_sub column to public_users (nullable for local users)
ALTER TABLE public_users 
    ADD COLUMN IF NOT EXISTS google_sub VARCHAR(255);

-- 2. Add auth_provider tracking (defaults to 'local' for existing users)
ALTER TABLE public_users 
    ADD COLUMN IF NOT EXISTS auth_provider VARCHAR(50) DEFAULT 'local';

-- 3. Create Pending OAuth Tickets Table for Replay Protection and Atomic Multi-Step Registration
CREATE TABLE IF NOT EXISTS pending_oauth_tickets (
    jti VARCHAR(64) PRIMARY KEY,
    google_sub VARCHAR(255) NOT NULL,
    email VARCHAR(255) NOT NULL,
    role VARCHAR(50) NOT NULL,
    is_consumed BOOLEAN NOT NULL DEFAULT FALSE,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Index on expires_at to facilitate efficient cleanup of expired tickets
CREATE INDEX IF NOT EXISTS idx_pending_oauth_tickets_expires_at 
    ON pending_oauth_tickets (expires_at);

-- 4. Post-Migration Step:
-- To enforce database-level uniqueness on google_sub without locking public_users in production,
-- execute the companion standalone script: 'migrations/015_google_sub_unique_index.sql'
-- in autocommit mode (outside of a transaction block).
