-- 012_phase4g_job_alert_preferences.sql
-- Non-destructive idempotent database migration for Phase 4G (Job Alert Preferences)

CREATE TABLE IF NOT EXISTS job_alert_preferences (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES public_users(id) ON DELETE CASCADE,
    is_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    departments TEXT[] DEFAULT '{}',
    job_roles TEXT[] DEFAULT '{}',
    locations TEXT[] DEFAULT '{}',
    job_types TEXT[] DEFAULT '{}',
    experience_min NUMERIC(4, 1) DEFAULT NULL,
    experience_max NUMERIC(4, 1) DEFAULT NULL,
    salary_min NUMERIC(12, 2) DEFAULT NULL,
    frequency VARCHAR(20) NOT NULL DEFAULT 'daily',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_job_alert_preferences_user UNIQUE (user_id)
);

CREATE INDEX IF NOT EXISTS idx_job_alert_pref_user_id ON job_alert_preferences(user_id);
CREATE INDEX IF NOT EXISTS idx_job_alert_pref_is_enabled ON job_alert_preferences(is_enabled);
