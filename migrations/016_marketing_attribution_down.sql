-- =============================================================================
-- Migration: 016_marketing_attribution_down.sql
-- Project:   DigiGarment – Phase 1D-4B Revert Marketing Attribution
-- =============================================================================
--
-- PURPOSE:
--   Reverts migration 016 by dropping `user_marketing_attributions`
--   and its associated indexes and constraints.
--
-- SAFETY & DEPENDENCY NOTICE (DB-01):
--   - Uses CASCADE to ensure any future dependent reporting views (e.g.,
--     analytics rollup views created in Phase 1D-4C) are cleaned up.
--   - CAUTION: In production, executing this script will permanently delete
--     all historical first-touch and last-touch marketing attribution data.
--   - Ensure a verified database backup is taken before executing this revert.
-- =============================================================================

DROP TABLE IF EXISTS user_marketing_attributions CASCADE;
