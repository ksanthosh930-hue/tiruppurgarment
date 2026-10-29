-- 013_job_seeker_analytics.sql
-- Non-destructive idempotent database migration for Job Seeker Analytics and Visitor Tracking
-- Preserves all existing tables, foreign keys, and indexes.

CREATE TABLE IF NOT EXISTS job_analytics_events (
    id SERIAL PRIMARY KEY,
    event_type VARCHAR(50) NOT NULL,
    job_id INTEGER REFERENCES jobs(id) ON DELETE CASCADE,
    visitor_id VARCHAR(64),
    user_id INTEGER REFERENCES public_users(id) ON DELETE SET NULL,
    session_id VARCHAR(64),
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_jae_event_type ON job_analytics_events(event_type);
CREATE INDEX IF NOT EXISTS idx_jae_created_at ON job_analytics_events(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_jae_job_id ON job_analytics_events(job_id);
CREATE INDEX IF NOT EXISTS idx_jae_visitor_id ON job_analytics_events(visitor_id);
CREATE INDEX IF NOT EXISTS idx_jae_user_id ON job_analytics_events(user_id);
CREATE INDEX IF NOT EXISTS idx_jae_event_created ON job_analytics_events(event_type, created_at DESC);
