-- =============================================================================
-- Migration: 016_marketing_attribution_up.sql
-- Project:   DigiGarment – Phase 1D-4B Marketing Attribution Foundation
-- Gate:      Phase 1D-4B-1 Implementation (DO NOT EXECUTE in production without authorization)
-- =============================================================================
--
-- PURPOSE:
--   Creates the dedicated `user_marketing_attributions` table to record deterministic
--   first-touch and last-touch marketing attribution for newly registered Job Seekers
--   (`account_type = 'individual'`) and Garment Employers (`account_type = 'company'`).
--
-- DESIGN HIGHLIGHTS:
--   1. 1:1 foreign key relationship to `public.public_users(id)` with ON DELETE CASCADE.
--   2. Strict user_id UNIQUE constraint guaranteeing exactly one attribution record per user.
--   3. Dual-touch attribution: first-touch (acquisition) and last-touch (conversion) preserved separately.
--   4. Zero bloat or schema changes on core `public.public_users` authentication table.
--   5. B-tree indexes for fast analytical slicing by account_type, source, campaign, and date.
--   6. Fully compatible with DPDP Act 2023 (Zero-PII marketing telemetry).
-- =============================================================================

CREATE TABLE IF NOT EXISTS user_marketing_attributions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES public_users(id) ON DELETE CASCADE,
    account_type VARCHAR(20) NOT NULL, -- 'individual' or 'company'

    -- First-Touch Attribution (Acquisition Source)
    first_utm_source VARCHAR(100),
    first_utm_medium VARCHAR(50),
    first_utm_campaign VARCHAR(150),
    first_utm_content VARCHAR(150),
    first_utm_term VARCHAR(150),
    first_landing_page TEXT,
    first_referrer TEXT,
    first_visit_at TIMESTAMP WITH TIME ZONE NOT NULL,

    -- Last-Touch Attribution (Conversion Trigger)
    last_utm_source VARCHAR(100),
    last_utm_medium VARCHAR(50),
    last_utm_campaign VARCHAR(150),
    last_utm_content VARCHAR(150),
    last_utm_term VARCHAR(150),
    last_landing_page TEXT,
    last_referrer TEXT,
    last_visit_at TIMESTAMP WITH TIME ZONE NOT NULL,

    -- Telemetry & Metadata
    visitor_id VARCHAR(64),
    registration_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    raw_metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT uq_user_marketing_attributions_user UNIQUE (user_id)
);

-- Performance Indexes for Real-Time Growth Analytics
CREATE INDEX IF NOT EXISTS idx_uma_account_first_source 
    ON user_marketing_attributions(account_type, first_utm_source);

CREATE INDEX IF NOT EXISTS idx_uma_account_last_source 
    ON user_marketing_attributions(account_type, last_utm_source);

CREATE INDEX IF NOT EXISTS idx_uma_account_campaign 
    ON user_marketing_attributions(account_type, first_utm_campaign);

CREATE INDEX IF NOT EXISTS idx_uma_reg_at 
    ON user_marketing_attributions(registration_at);

CREATE INDEX IF NOT EXISTS idx_uma_visitor_id 
    ON user_marketing_attributions(visitor_id);
