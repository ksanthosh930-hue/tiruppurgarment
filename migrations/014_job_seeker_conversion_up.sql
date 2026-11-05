-- =============================================================================
-- Migration: 014_job_seeker_conversion_up.sql
-- Project:   DigiGarment – Job Seeker Registration & Conversion Optimization
-- Gate:      Prepared in Gate B / Corrected in Gate B.1, Gate B.2 & Gate B.3
--            (DO NOT EXECUTE until Gate C Approval)
-- =============================================================================
--
-- PURPOSE & SCOPE (SCHEMA ONLY — NO DATA SEEDING):
--   1. Structurally verifies that the existing partial unique index
--      `idx_job_app_unique_candidate` on `public.job_applications` exists in
--      schema `public`, belongs to ordinary permanent table `public.job_applications`,
--      uses `btree`, is unique/valid/ready/live and non-primary, has key columns
--      `['job_id', 'candidate_user_id']` with ascending options `[0, 0]`, has no
--      expression keys, and has exact partial predicate
--      `(candidate_user_id IS NOT NULL)` (Decision D1).
--      Never creates a duplicate index on `job_applications`.
--   2. Adds nullable `event_id VARCHAR(128)` to `public.job_analytics_events`
--      if absent and marks it with catalog comment
--      `created_by_migration:014_job_seeker_conversion`. If `event_id` already
--      exists, verifies its exact data type, VARCHAR(128) length, nullability,
--      NULL default, and non-conflicting ownership comment WITHOUT overwriting
--      its catalog comment (never claims ownership of a pre-existing column).
--   3. Creates partial unique index `idx_job_analytics_events_event_id_unique`
--      if absent and marks it as created by migration 014. If pre-existing,
--      verifies it structurally via `pg_index`, `pg_class`, `pg_namespace`
--      (both index schema and underlying table schema = `'public'`), `pg_am`,
--      `pg_attribute`, `indkey`, `indoption`, `pg_get_expr(ix.indpred, ix.indrelid)`,
--      and non-conflicting ownership comment WITHOUT overwriting its catalog comment.
--   4. Creates `public.legacy_profile_migration_map` if absent and marks it as
--      created by migration 014. If pre-existing, inspects PostgreSQL catalogs
--      (`pg_class`, `information_schema.columns`, `pg_constraint`, `pg_attribute`,
--      `pg_index`) to verify:
--        - Ordinary permanent table (`relkind = 'r'`, `relpersistence = 'p'`),
--        - All 9 columns (types, VARCHAR(40) length, nullability, and defaults),
--        - Primary key definition and backing index state (`indisvalid`, `indisready`,
--          `indislive`, `indisunique`, `indisprimary`),
--        - Both unique constraint definitions and backing index states,
--        - All 4 foreign key targets, schemas, columns, `ON DELETE` actions
--          (`RESTRICT` / `SET NULL`), `ON UPDATE` actions, and validation state,
--        - All 3 CHECK constraint expressions using full-expression structural
--          verification and exact literal array extraction (enforcing Decision D3),
--        - Non-conflicting ownership comment WITHOUT claiming ownership of a
--          pre-existing table.
--   5. Structurally creates or verifies the 3 supporting lookup indexes on
--      `public.legacy_profile_migration_map` (`idx_lpmm_mapped_public_user_id`,
--      `idx_lpmm_mapped_ind_profile_id`, `idx_lpmm_migration_status`), verifying
--      both index schema and underlying table schema (`'public'`), catalog state
--      flags (`indisvalid`, `indisready`, `indisunique`, `indislive`, `indisprimary`),
--      key columns, key options, and exact partial predicates, marking only newly
--      created indexes as owned by migration 014.
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- 0. Structural Pre-Flight Verification of `idx_job_app_unique_candidate` (D1)
-- -----------------------------------------------------------------------------
DO $$
DECLARE
    v_idx_schema   TEXT;
    v_tbl_schema   TEXT;
    v_tbl_name     TEXT;
    v_tbl_relkind  "char";
    v_tbl_persist  "char";
    v_am_name      TEXT;
    v_is_unique    BOOLEAN;
    v_is_prim      BOOLEAN;
    v_is_valid     BOOLEAN;
    v_is_ready     BOOLEAN;
    v_is_live      BOOLEAN;
    v_natts        SMALLINT;
    v_nkeyatts     SMALLINT;
    v_has_exprs    BOOLEAN;
    v_key_cols     TEXT[];
    v_key_opts     INT4[];
    v_pred_expr    TEXT;
BEGIN
    SELECT n.nspname,
           tn.nspname,
           t.relname,
           t.relkind,
           t.relpersistence,
           am.amname,
           ix.indisunique,
           ix.indisprimary,
           ix.indisvalid,
           ix.indisready,
           ix.indislive,
           ix.indnatts,
           ix.indnkeyatts,
           (ix.indexprs IS NOT NULL),
           ARRAY(
               SELECT a.attname::text
                 FROM unnest(ix.indkey::smallint[]) WITH ORDINALITY AS k(attnum, ord)
                 JOIN pg_attribute a
                   ON a.attrelid = ix.indrelid
                  AND a.attnum = k.attnum
                WHERE k.ord <= ix.indnkeyatts
                ORDER BY k.ord
           ),
           ARRAY(
               SELECT o.opt::int4
                 FROM unnest(ix.indoption::smallint[]) WITH ORDINALITY AS o(opt, ord)
                WHERE o.ord <= ix.indnkeyatts
                ORDER BY o.ord
           ),
           pg_get_expr(ix.indpred, ix.indrelid)
      INTO v_idx_schema,
           v_tbl_schema,
           v_tbl_name,
           v_tbl_relkind,
           v_tbl_persist,
           v_am_name,
           v_is_unique,
           v_is_prim,
           v_is_valid,
           v_is_ready,
           v_is_live,
           v_natts,
           v_nkeyatts,
           v_has_exprs,
           v_key_cols,
           v_key_opts,
           v_pred_expr
      FROM pg_index ix
      JOIN pg_class i ON i.oid = ix.indexrelid
      JOIN pg_namespace n ON n.oid = i.relnamespace
      JOIN pg_am am ON am.oid = i.relam
      JOIN pg_class t ON t.oid = ix.indrelid
      JOIN pg_namespace tn ON tn.oid = t.relnamespace
     WHERE n.nspname = 'public'
       AND i.relname = 'idx_job_app_unique_candidate'
       AND i.relkind = 'i';

    IF NOT FOUND THEN
        RAISE EXCEPTION
            'Pre-flight check failed: expected existing index public.idx_job_app_unique_candidate on public.job_applications was not found.';
    END IF;

    IF v_idx_schema IS DISTINCT FROM 'public'
       OR v_tbl_schema IS DISTINCT FROM 'public'
       OR v_tbl_name IS DISTINCT FROM 'job_applications'
       OR v_tbl_relkind IS DISTINCT FROM 'r'
       OR v_tbl_persist IS DISTINCT FROM 'p'
       OR v_am_name IS DISTINCT FROM 'btree'
       OR v_is_unique IS DISTINCT FROM TRUE
       OR v_is_prim IS DISTINCT FROM FALSE
       OR v_is_valid IS DISTINCT FROM TRUE
       OR v_is_ready IS DISTINCT FROM TRUE
       OR v_is_live IS DISTINCT FROM TRUE
       OR v_natts IS DISTINCT FROM 2
       OR v_nkeyatts IS DISTINCT FROM 2
       OR v_has_exprs IS DISTINCT FROM FALSE
       OR v_key_cols IS DISTINCT FROM ARRAY['job_id', 'candidate_user_id']::text[]
       OR v_key_opts IS DISTINCT FROM ARRAY[0, 0]::int4[]
       OR v_pred_expr IS DISTINCT FROM '(candidate_user_id IS NOT NULL)' THEN
        RAISE EXCEPTION
            'Pre-flight check failed: idx_job_app_unique_candidate structural mismatch (idx_schema=%, tbl_schema=%, table=%, relkind=%, persist=%, am=%, unique=%, primary=%, valid=%, ready=%, live=%, natts=%, nkeyatts=%, exprs=%, cols=%, opts=%, pred=%).',
            v_idx_schema, v_tbl_schema, v_tbl_name, v_tbl_relkind, v_tbl_persist,
            v_am_name, v_is_unique, v_is_prim, v_is_valid, v_is_ready, v_is_live,
            v_natts, v_nkeyatts, v_has_exprs, v_key_cols, v_key_opts, v_pred_expr;
    END IF;
END $$;

-- -----------------------------------------------------------------------------
-- 1. Add or Verify `event_id VARCHAR(128)` on `public.job_analytics_events`
-- -----------------------------------------------------------------------------
DO $$
DECLARE
    v_jae_oid      OID;
    v_jae_relkind  "char";
    v_jae_persist  "char";
    v_attnum       SMALLINT;
    v_col_comment  TEXT;
    v_data_type    TEXT;
    v_udt_name     TEXT;
    v_max_len      INTEGER;
    v_is_nullable  TEXT;
    v_col_default  TEXT;
BEGIN
    SELECT c.oid,
           c.relkind,
           c.relpersistence
      INTO v_jae_oid,
           v_jae_relkind,
           v_jae_persist
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'public'
       AND c.relname = 'job_analytics_events';

    IF NOT FOUND
       OR v_jae_relkind IS DISTINCT FROM 'r'
       OR v_jae_persist IS DISTINCT FROM 'p' THEN
        RAISE EXCEPTION
            'Pre-flight check failed: public.job_analytics_events must exist as an ordinary permanent table (relkind=%, relpersistence=%).',
            v_jae_relkind, v_jae_persist;
    END IF;

    SELECT c.data_type,
           c.udt_name,
           c.character_maximum_length,
           c.is_nullable,
           c.column_default
      INTO v_data_type,
           v_udt_name,
           v_max_len,
           v_is_nullable,
           v_col_default
      FROM information_schema.columns c
     WHERE c.table_schema = 'public'
       AND c.table_name = 'job_analytics_events'
       AND c.column_name = 'event_id';

    IF NOT FOUND THEN
        ALTER TABLE public.job_analytics_events
            ADD COLUMN event_id VARCHAR(128) NULL;

        COMMENT ON COLUMN public.job_analytics_events.event_id
            IS 'created_by_migration:014_job_seeker_conversion';
    ELSE
        -- Pre-existing column: verify exact definition and NEVER overwrite a pre-existing NULL comment
        IF v_data_type IS DISTINCT FROM 'character varying'
           OR v_udt_name IS DISTINCT FROM 'varchar'
           OR v_max_len IS DISTINCT FROM 128
           OR v_is_nullable IS DISTINCT FROM 'YES'
           OR v_col_default IS NOT NULL THEN
            RAISE EXCEPTION
                'Schema verification failed: pre-existing public.job_analytics_events.event_id has unexpected definition (type=%, udt=%, length=%, nullable=%, default=%). Expected VARCHAR(128) NULL with no default.',
                v_data_type, v_udt_name, v_max_len, v_is_nullable, v_col_default;
        END IF;

        SELECT a.attnum
          INTO v_attnum
          FROM pg_attribute a
         WHERE a.attrelid = v_jae_oid
           AND a.attname = 'event_id'
           AND NOT a.attisdropped;

        SELECT col_description(v_jae_oid, v_attnum)
          INTO v_col_comment;

        IF v_col_comment IS NOT NULL
           AND v_col_comment IS DISTINCT FROM 'created_by_migration:014_job_seeker_conversion' THEN
            RAISE EXCEPTION
                'Schema verification failed: pre-existing public.job_analytics_events.event_id has conflicting catalog comment (%).',
                v_col_comment;
        END IF;
    END IF;
END $$;

-- -----------------------------------------------------------------------------
-- 2. Create or Structurally Verify `idx_job_analytics_events_event_id_unique`
-- -----------------------------------------------------------------------------
DO $$
DECLARE
    v_idx_oid      OID;
    v_idx_schema   TEXT;
    v_table_schema TEXT;
    v_table_name   TEXT;
    v_relkind      "char";
    v_am_name      TEXT;
    v_is_unique    BOOLEAN;
    v_is_prim      BOOLEAN;
    v_is_valid     BOOLEAN;
    v_is_ready     BOOLEAN;
    v_is_live      BOOLEAN;
    v_natts        SMALLINT;
    v_nkeyatts     SMALLINT;
    v_has_exprs    BOOLEAN;
    v_key_cols     TEXT[];
    v_key_opts     INT4[];
    v_pred_expr    TEXT;
    v_idx_comment  TEXT;
BEGIN
    SELECT i.oid,
           n.nspname,
           tn.nspname,
           t.relname,
           i.relkind,
           am.amname,
           ix.indisunique,
           ix.indisprimary,
           ix.indisvalid,
           ix.indisready,
           ix.indislive,
           ix.indnatts,
           ix.indnkeyatts,
           (ix.indexprs IS NOT NULL),
           ARRAY(
               SELECT a.attname::text
                 FROM unnest(ix.indkey::smallint[]) WITH ORDINALITY AS k(attnum, ord)
                 JOIN pg_attribute a
                   ON a.attrelid = ix.indrelid
                  AND a.attnum = k.attnum
                WHERE k.ord <= ix.indnkeyatts
                ORDER BY k.ord
           ),
           ARRAY(
               SELECT o.opt::int4
                 FROM unnest(ix.indoption::smallint[]) WITH ORDINALITY AS o(opt, ord)
                WHERE o.ord <= ix.indnkeyatts
                ORDER BY o.ord
           ),
           pg_get_expr(ix.indpred, ix.indrelid)
      INTO v_idx_oid,
           v_idx_schema,
           v_table_schema,
           v_table_name,
           v_relkind,
           v_am_name,
           v_is_unique,
           v_is_prim,
           v_is_valid,
           v_is_ready,
           v_is_live,
           v_natts,
           v_nkeyatts,
           v_has_exprs,
           v_key_cols,
           v_key_opts,
           v_pred_expr
      FROM pg_class i
      JOIN pg_namespace n ON n.oid = i.relnamespace
      LEFT JOIN pg_am am ON am.oid = i.relam
      LEFT JOIN pg_index ix ON ix.indexrelid = i.oid
      LEFT JOIN pg_class t ON t.oid = ix.indrelid
      LEFT JOIN pg_namespace tn ON tn.oid = t.relnamespace
     WHERE n.nspname = 'public'
       AND i.relname = 'idx_job_analytics_events_event_id_unique';

    IF NOT FOUND THEN
        CREATE UNIQUE INDEX idx_job_analytics_events_event_id_unique
            ON public.job_analytics_events (event_id)
            WHERE event_id IS NOT NULL;

        COMMENT ON INDEX public.idx_job_analytics_events_event_id_unique
            IS 'created_by_migration:014_job_seeker_conversion';
    ELSE
        -- Pre-existing index: verify structurally and NEVER overwrite a pre-existing NULL comment
        IF v_idx_schema IS DISTINCT FROM 'public'
           OR v_relkind IS DISTINCT FROM 'i'
           OR v_table_schema IS DISTINCT FROM 'public'
           OR v_table_name IS DISTINCT FROM 'job_analytics_events'
           OR v_am_name IS DISTINCT FROM 'btree'
           OR v_is_unique IS DISTINCT FROM TRUE
           OR v_is_prim IS DISTINCT FROM FALSE
           OR v_is_valid IS DISTINCT FROM TRUE
           OR v_is_ready IS DISTINCT FROM TRUE
           OR v_is_live IS DISTINCT FROM TRUE
           OR v_natts IS DISTINCT FROM 1
           OR v_nkeyatts IS DISTINCT FROM 1
           OR v_has_exprs IS DISTINCT FROM FALSE
           OR v_key_cols IS DISTINCT FROM ARRAY['event_id']::text[]
           OR v_key_opts IS DISTINCT FROM ARRAY[0]::int4[]
           OR v_pred_expr IS DISTINCT FROM '(event_id IS NOT NULL)' THEN
            RAISE EXCEPTION
                'Schema verification failed: pre-existing idx_job_analytics_events_event_id_unique has structural mismatch (idx_schema=%, tbl_schema=%, table=%, relkind=%, am=%, unique=%, primary=%, valid=%, ready=%, live=%, natts=%, nkeyatts=%, exprs=%, cols=%, opts=%, pred=%).',
                v_idx_schema, v_table_schema, v_table_name, v_relkind, v_am_name,
                v_is_unique, v_is_prim, v_is_valid, v_is_ready, v_is_live,
                v_natts, v_nkeyatts, v_has_exprs, v_key_cols, v_key_opts, v_pred_expr;
        END IF;

        SELECT obj_description(v_idx_oid, 'pg_class')
          INTO v_idx_comment;

        IF v_idx_comment IS NOT NULL
           AND v_idx_comment IS DISTINCT FROM 'created_by_migration:014_job_seeker_conversion' THEN
            RAISE EXCEPTION
                'Schema verification failed: pre-existing idx_job_analytics_events_event_id_unique has conflicting catalog comment (%).',
                v_idx_comment;
        END IF;
    END IF;
END $$;

-- -----------------------------------------------------------------------------
-- 3. Create or Structurally Verify `public.legacy_profile_migration_map`
-- -----------------------------------------------------------------------------
DO $$
DECLARE
    v_lpmm_oid         OID;
    v_lpmm_relkind     "char";
    v_lpmm_persist     "char";
    v_lpmm_comment     TEXT;
    v_col_count        INTEGER;
    v_missing_cols     TEXT;
    v_total_cons       INTEGER;
    v_fk_count         INTEGER;

    v_pk_cols          TEXT[];
    v_pk_con_val       BOOLEAN;
    v_pk_valid         BOOLEAN;
    v_pk_ready         BOOLEAN;
    v_pk_live          BOOLEAN;
    v_pk_unique        BOOLEAN;
    v_pk_prim          BOOLEAN;

    v_uq_jsp_cols      TEXT[];
    v_uq_jsp_con_val   BOOLEAN;
    v_uq_jsp_valid     BOOLEAN;
    v_uq_jsp_ready     BOOLEAN;
    v_uq_jsp_live      BOOLEAN;
    v_uq_jsp_unique    BOOLEAN;
    v_uq_jsp_prim      BOOLEAN;

    v_uq_usr_cols      TEXT[];
    v_uq_usr_con_val   BOOLEAN;
    v_uq_usr_valid     BOOLEAN;
    v_uq_usr_ready     BOOLEAN;
    v_uq_usr_live      BOOLEAN;
    v_uq_usr_unique    BOOLEAN;
    v_uq_usr_prim      BOOLEAN;

    v_missing_fks      TEXT;

    v_chk_status_expr  TEXT;
    v_chk_status_norm  TEXT;
    v_chk_status_lits  TEXT[];
    v_chk_status_cols  TEXT[];
    v_chk_status_val   BOOLEAN;

    v_chk_d3_expr      TEXT;
    v_chk_d3_norm      TEXT;
    v_chk_d3_lits      TEXT[];
    v_chk_d3_cols      TEXT[];
    v_chk_d3_val       BOOLEAN;

    v_chk_link_expr    TEXT;
    v_chk_link_norm    TEXT;
    v_chk_link_lits    TEXT[];
    v_chk_link_cols    TEXT[];
    v_chk_link_val     BOOLEAN;
BEGIN
    SELECT c.oid,
           c.relkind,
           c.relpersistence
      INTO v_lpmm_oid,
           v_lpmm_relkind,
           v_lpmm_persist
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'public'
       AND c.relname = 'legacy_profile_migration_map';

    IF NOT FOUND THEN
        CREATE TABLE public.legacy_profile_migration_map (
            id SERIAL PRIMARY KEY,
            legacy_user_id INTEGER NOT NULL
                CONSTRAINT lpmm_legacy_user_id_fkey
                REFERENCES public.users(id) ON DELETE RESTRICT,
            legacy_job_seeker_profile_id INTEGER NOT NULL
                CONSTRAINT lpmm_legacy_jsp_id_fkey
                REFERENCES public.job_seeker_profiles(id) ON DELETE RESTRICT,
            mapped_public_user_id INTEGER NULL
                CONSTRAINT lpmm_mapped_public_user_id_fkey
                REFERENCES public.public_users(id) ON DELETE SET NULL,
            mapped_individual_profile_id INTEGER NULL
                CONSTRAINT lpmm_mapped_individual_profile_id_fkey
                REFERENCES public.individual_profiles(id) ON DELETE SET NULL,
            migration_status VARCHAR(40) NOT NULL DEFAULT 'pending_audit',
            conflict_reason TEXT NULL,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

            -- One mapping entry per legacy job_seeker_profiles record and legacy users record
            CONSTRAINT uq_lpmm_legacy_jsp_id UNIQUE (legacy_job_seeker_profile_id),
            CONSTRAINT uq_lpmm_legacy_user_id UNIQUE (legacy_user_id),

            -- Allowed migration statuses
            CONSTRAINT chk_lpmm_migration_status CHECK (
                migration_status IN (
                    'pending_audit',
                    'linked_readonly',
                    'unmatched_preserved',
                    'conflict_pending_manual_review',
                    'invalid_mobile_preserved',
                    'manually_resolved'
                )
            ),

            -- Decision D3 Safeguard: Non-linked / probable / conflicting statuses
            -- MUST NOT have mapped_public_user_id or mapped_individual_profile_id populated.
            CONSTRAINT chk_lpmm_probable_conflict_not_linked CHECK (
                migration_status NOT IN (
                    'pending_audit',
                    'unmatched_preserved',
                    'conflict_pending_manual_review',
                    'invalid_mobile_preserved'
                )
                OR (mapped_public_user_id IS NULL AND mapped_individual_profile_id IS NULL)
            ),

            -- Consistency check: if status is `linked_readonly`, both mapped IDs must be present
            CONSTRAINT chk_lpmm_linked_requires_targets CHECK (
                migration_status <> 'linked_readonly'
                OR (mapped_public_user_id IS NOT NULL AND mapped_individual_profile_id IS NOT NULL)
            )
        );

        COMMENT ON TABLE public.legacy_profile_migration_map
            IS 'created_by_migration:014_job_seeker_conversion';
    ELSE
        -- =====================================================================
        -- Pre-existing table: full catalog verification WITHOUT claiming ownership
        -- =====================================================================
        IF v_lpmm_relkind IS DISTINCT FROM 'r'
           OR v_lpmm_persist IS DISTINCT FROM 'p' THEN
            RAISE EXCEPTION
                'Schema verification failed: pre-existing public.legacy_profile_migration_map is not an ordinary permanent table (relkind=%, relpersistence=%).',
                v_lpmm_relkind, v_lpmm_persist;
        END IF;

        SELECT obj_description(v_lpmm_oid, 'pg_class')
          INTO v_lpmm_comment;

        IF v_lpmm_comment IS NOT NULL
           AND v_lpmm_comment IS DISTINCT FROM 'created_by_migration:014_job_seeker_conversion' THEN
            RAISE EXCEPTION
                'Schema verification failed: pre-existing public.legacy_profile_migration_map has conflicting catalog comment (%).',
                v_lpmm_comment;
        END IF;

        -- 3A. Verify exact 9 columns, types, VARCHAR(40) length, nullability, and defaults
        WITH expected_cols (col_name, data_type, udt_name, max_len, is_nullable, default_kind) AS (
            VALUES
                ('id',                           'integer',                     'int4',      NULL::int, 'NO',  'SEQ'),
                ('legacy_user_id',               'integer',                     'int4',      NULL::int, 'NO',  'NULL'),
                ('legacy_job_seeker_profile_id', 'integer',                     'int4',      NULL::int, 'NO',  'NULL'),
                ('mapped_public_user_id',        'integer',                     'int4',      NULL::int, 'YES', 'NULL'),
                ('mapped_individual_profile_id', 'integer',                     'int4',      NULL::int, 'YES', 'NULL'),
                ('migration_status',             'character varying',           'varchar',   40,        'NO',  'PENDING_AUDIT'),
                ('conflict_reason',              'text',                        'text',      NULL::int, 'YES', 'NULL'),
                ('created_at',                   'timestamp without time zone', 'timestamp', NULL::int, 'NO',  'NOW'),
                ('updated_at',                   'timestamp without time zone', 'timestamp', NULL::int, 'NO',  'NOW')
        )
        SELECT string_agg(e.col_name, ', ')
          INTO v_missing_cols
          FROM expected_cols e
          LEFT JOIN information_schema.columns c
            ON c.table_schema = 'public'
           AND c.table_name = 'legacy_profile_migration_map'
           AND c.column_name = e.col_name
           AND c.data_type = e.data_type
           AND c.udt_name = e.udt_name
           AND c.character_maximum_length IS NOT DISTINCT FROM e.max_len
           AND c.is_nullable = e.is_nullable
           AND (
               (e.default_kind = 'NULL' AND c.column_default IS NULL)
               OR (e.default_kind = 'SEQ' AND c.column_default LIKE 'nextval(%legacy_profile_migration_map_id_seq%' AND c.column_default LIKE '%::regclass)')
               OR (e.default_kind = 'PENDING_AUDIT' AND btrim(c.column_default) IN ('''pending_audit''::character varying', '''pending_audit'''))
               OR (e.default_kind = 'NOW' AND upper(btrim(c.column_default)) IN ('CURRENT_TIMESTAMP', 'NOW()'))
           )
         WHERE c.column_name IS NULL;

        IF v_missing_cols IS NOT NULL THEN
            RAISE EXCEPTION
                'Schema verification failed: pre-existing public.legacy_profile_migration_map has missing or mismatched column/type/length/nullability/default definition(s): %',
                v_missing_cols;
        END IF;

        SELECT COUNT(*)
          INTO v_col_count
          FROM information_schema.columns
         WHERE table_schema = 'public'
           AND table_name = 'legacy_profile_migration_map';

        IF v_col_count IS DISTINCT FROM 9 THEN
            RAISE EXCEPTION
                'Schema verification failed: pre-existing public.legacy_profile_migration_map has % columns (expected exactly 9).',
                v_col_count;
        END IF;

        -- 3B. Verify Primary Key (`legacy_profile_migration_map_pkey` on `id`) & backing index state
        SELECT ARRAY(
                   SELECT a.attname::text
                     FROM unnest(con.conkey) WITH ORDINALITY AS k(attnum, ord)
                     JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = k.attnum
                    ORDER BY k.ord
               ),
               con.convalidated,
               ix.indisvalid,
               ix.indisready,
               ix.indislive,
               ix.indisunique,
               ix.indisprimary
          INTO v_pk_cols,
               v_pk_con_val,
               v_pk_valid,
               v_pk_ready,
               v_pk_live,
               v_pk_unique,
               v_pk_prim
          FROM pg_constraint con
          JOIN pg_index ix ON ix.indexrelid = con.conindid
         WHERE con.conrelid = v_lpmm_oid
           AND con.conname = 'legacy_profile_migration_map_pkey'
           AND con.contype = 'p';

        IF NOT FOUND
           OR v_pk_cols IS DISTINCT FROM ARRAY['id']::text[]
           OR v_pk_con_val IS DISTINCT FROM TRUE
           OR v_pk_valid IS DISTINCT FROM TRUE
           OR v_pk_ready IS DISTINCT FROM TRUE
           OR v_pk_live IS DISTINCT FROM TRUE
           OR v_pk_unique IS DISTINCT FROM TRUE
           OR v_pk_prim IS DISTINCT FROM TRUE THEN
            RAISE EXCEPTION
                'Schema verification failed: legacy_profile_migration_map_pkey is missing, invalid, or does not cover (id) (cols=%, validated=%, valid=%, ready=%, live=%, unique=%, primary=%).',
                v_pk_cols, v_pk_con_val, v_pk_valid, v_pk_ready, v_pk_live, v_pk_unique, v_pk_prim;
        END IF;

        -- 3C. Verify Both Unique Constraints (`uq_lpmm_legacy_jsp_id` and `uq_lpmm_legacy_user_id`) & backing index states
        SELECT ARRAY(
                   SELECT a.attname::text
                     FROM unnest(con.conkey) WITH ORDINALITY AS k(attnum, ord)
                     JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = k.attnum
                    ORDER BY k.ord
               ),
               con.convalidated,
               ix.indisvalid,
               ix.indisready,
               ix.indislive,
               ix.indisunique,
               ix.indisprimary
          INTO v_uq_jsp_cols,
               v_uq_jsp_con_val,
               v_uq_jsp_valid,
               v_uq_jsp_ready,
               v_uq_jsp_live,
               v_uq_jsp_unique,
               v_uq_jsp_prim
          FROM pg_constraint con
          JOIN pg_index ix ON ix.indexrelid = con.conindid
         WHERE con.conrelid = v_lpmm_oid
           AND con.conname = 'uq_lpmm_legacy_jsp_id'
           AND con.contype = 'u';

        IF NOT FOUND
           OR v_uq_jsp_cols IS DISTINCT FROM ARRAY['legacy_job_seeker_profile_id']::text[]
           OR v_uq_jsp_con_val IS DISTINCT FROM TRUE
           OR v_uq_jsp_valid IS DISTINCT FROM TRUE
           OR v_uq_jsp_ready IS DISTINCT FROM TRUE
           OR v_uq_jsp_live IS DISTINCT FROM TRUE
           OR v_uq_jsp_unique IS DISTINCT FROM TRUE
           OR v_uq_jsp_prim IS DISTINCT FROM FALSE THEN
            RAISE EXCEPTION
                'Schema verification failed: uq_lpmm_legacy_jsp_id is missing, invalid, or does not cover (legacy_job_seeker_profile_id) (cols=%, validated=%, valid=%, ready=%, live=%, unique=%, primary=%).',
                v_uq_jsp_cols, v_uq_jsp_con_val, v_uq_jsp_valid, v_uq_jsp_ready, v_uq_jsp_live, v_uq_jsp_unique, v_uq_jsp_prim;
        END IF;

        SELECT ARRAY(
                   SELECT a.attname::text
                     FROM unnest(con.conkey) WITH ORDINALITY AS k(attnum, ord)
                     JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = k.attnum
                    ORDER BY k.ord
               ),
               con.convalidated,
               ix.indisvalid,
               ix.indisready,
               ix.indislive,
               ix.indisunique,
               ix.indisprimary
          INTO v_uq_usr_cols,
               v_uq_usr_con_val,
               v_uq_usr_valid,
               v_uq_usr_ready,
               v_uq_usr_live,
               v_uq_usr_unique,
               v_uq_usr_prim
          FROM pg_constraint con
          JOIN pg_index ix ON ix.indexrelid = con.conindid
         WHERE con.conrelid = v_lpmm_oid
           AND con.conname = 'uq_lpmm_legacy_user_id'
           AND con.contype = 'u';

        IF NOT FOUND
           OR v_uq_usr_cols IS DISTINCT FROM ARRAY['legacy_user_id']::text[]
           OR v_uq_usr_con_val IS DISTINCT FROM TRUE
           OR v_uq_usr_valid IS DISTINCT FROM TRUE
           OR v_uq_usr_ready IS DISTINCT FROM TRUE
           OR v_uq_usr_live IS DISTINCT FROM TRUE
           OR v_uq_usr_unique IS DISTINCT FROM TRUE
           OR v_uq_usr_prim IS DISTINCT FROM FALSE THEN
            RAISE EXCEPTION
                'Schema verification failed: uq_lpmm_legacy_user_id is missing, invalid, or does not cover (legacy_user_id) (cols=%, validated=%, valid=%, ready=%, live=%, unique=%, primary=%).',
                v_uq_usr_cols, v_uq_usr_con_val, v_uq_usr_valid, v_uq_usr_ready, v_uq_usr_live, v_uq_usr_unique, v_uq_usr_prim;
        END IF;

        -- 3D. Verify All 4 Foreign Keys (source column, target schema/table, target column, ON DELETE, ON UPDATE, deferrability, validated)
        WITH expected_fks (con_name, src_cols, ref_schema, ref_table, ref_cols, del_action, upd_action) AS (
            VALUES
                ('lpmm_legacy_user_id_fkey',               ARRAY['legacy_user_id']::text[],               'public', 'users',               ARRAY['id']::text[], 'r'::"char", 'a'::"char"),
                ('lpmm_legacy_jsp_id_fkey',                ARRAY['legacy_job_seeker_profile_id']::text[], 'public', 'job_seeker_profiles', ARRAY['id']::text[], 'r'::"char", 'a'::"char"),
                ('lpmm_mapped_public_user_id_fkey',        ARRAY['mapped_public_user_id']::text[],        'public', 'public_users',        ARRAY['id']::text[], 'n'::"char", 'a'::"char"),
                ('lpmm_mapped_individual_profile_id_fkey', ARRAY['mapped_individual_profile_id']::text[], 'public', 'individual_profiles', ARRAY['id']::text[], 'n'::"char", 'a'::"char")
        ),
        actual_fks AS (
            SELECT con.conname,
                   con.convalidated,
                   con.condeferrable,
                   con.condeferred,
                   rn.nspname AS ref_schema,
                   rc.relname AS ref_table,
                   con.confdeltype,
                   con.confupdtype,
                   ARRAY(
                       SELECT a.attname::text
                         FROM unnest(con.conkey) WITH ORDINALITY AS k(attnum, ord)
                         JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = k.attnum
                        ORDER BY k.ord
                   ) AS src_cols,
                   ARRAY(
                       SELECT a.attname::text
                         FROM unnest(con.confkey) WITH ORDINALITY AS k(attnum, ord)
                         JOIN pg_attribute a ON a.attrelid = con.confrelid AND a.attnum = k.attnum
                        ORDER BY k.ord
                   ) AS ref_cols
              FROM pg_constraint con
              JOIN pg_class rc ON rc.oid = con.confrelid
              JOIN pg_namespace rn ON rn.oid = rc.relnamespace
             WHERE con.conrelid = v_lpmm_oid
               AND con.contype = 'f'
        )
        SELECT string_agg(ef.con_name, ', ')
          INTO v_missing_fks
          FROM expected_fks ef
          LEFT JOIN actual_fks af
            ON af.conname = ef.con_name
           AND af.convalidated = TRUE
           AND af.condeferrable = FALSE
           AND af.condeferred = FALSE
           AND af.src_cols = ef.src_cols
           AND af.ref_schema = ef.ref_schema
           AND af.ref_table = ef.ref_table
           AND af.ref_cols = ef.ref_cols
           AND af.confdeltype = ef.del_action
           AND af.confupdtype = ef.upd_action
         WHERE af.conname IS NULL;

        IF v_missing_fks IS NOT NULL THEN
            RAISE EXCEPTION
                'Schema verification failed: pre-existing public.legacy_profile_migration_map has missing or mismatched foreign key definition(s) (target/schema/columns/ON DELETE/ON UPDATE/validated): %',
                v_missing_fks;
        END IF;

        SELECT COUNT(*)
          INTO v_fk_count
          FROM pg_constraint con
         WHERE con.conrelid = v_lpmm_oid
           AND con.contype = 'f';

        IF v_fk_count IS DISTINCT FROM 4 THEN
            RAISE EXCEPTION
                'Schema verification failed: pre-existing public.legacy_profile_migration_map has % foreign key constraints (expected exactly 4).',
                v_fk_count;
        END IF;

        -- 3E. Complete Structural & Exact Literal-Set Verification of All 3 CHECK Constraints
        --     (Rejects any weakened, modified, or extra-clause expression)

        -- Check 1: `chk_lpmm_migration_status`
        SELECT con.convalidated,
               ARRAY(
                   SELECT a.attname::text
                     FROM unnest(con.conkey) AS k(attnum)
                     JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = k.attnum
                    ORDER BY a.attname
               ),
               regexp_replace(pg_get_expr(con.conbin, con.conrelid), '\s+', ' ', 'g')
          INTO v_chk_status_val,
               v_chk_status_cols,
               v_chk_status_expr
          FROM pg_constraint con
         WHERE con.conrelid = v_lpmm_oid
           AND con.conname = 'chk_lpmm_migration_status'
           AND con.contype = 'c';

        IF NOT FOUND THEN
            RAISE EXCEPTION
                'Schema verification failed: CHECK constraint chk_lpmm_migration_status is missing on public.legacy_profile_migration_map.';
        END IF;

        -- Extract exact ordered string literals from the decompiled AST
        SELECT ARRAY(
                   SELECT m[1]
                     FROM regexp_matches(v_chk_status_expr, '''([^'']+)''', 'g') WITH ORDINALITY AS t(m, ord)
                    ORDER BY t.ord
               )
          INTO v_chk_status_lits;

        -- Normalize only PostgreSQL type-cast decorations and parentheses for full-expression comparison
        v_chk_status_norm := btrim(
            regexp_replace(
                regexp_replace(
                    regexp_replace(v_chk_status_expr, '::character varying(\[\])?|::varchar(\[\])?|::text(\[\])?', '', 'g'),
                    '[()]', '', 'g'
                ),
                '\s+', ' ', 'g'
            )
        );

        IF v_chk_status_val IS DISTINCT FROM TRUE
           OR v_chk_status_cols IS DISTINCT FROM ARRAY['migration_status']::text[]
           OR v_chk_status_lits IS DISTINCT FROM ARRAY[
               'pending_audit',
               'linked_readonly',
               'unmatched_preserved',
               'conflict_pending_manual_review',
               'invalid_mobile_preserved',
               'manually_resolved'
           ]::text[]
           OR v_chk_status_norm IS DISTINCT FROM
              'migration_status = ANY ARRAY[''pending_audit'', ''linked_readonly'', ''unmatched_preserved'', ''conflict_pending_manual_review'', ''invalid_mobile_preserved'', ''manually_resolved'']' THEN
            RAISE EXCEPTION
                'Schema verification failed: chk_lpmm_migration_status failed complete structural verification (validated=%, cols=%, literals=%, normalized_expr=%, raw_expr=%).',
                v_chk_status_val, v_chk_status_cols, v_chk_status_lits, v_chk_status_norm, v_chk_status_expr;
        END IF;

        -- Check 2: `chk_lpmm_probable_conflict_not_linked` (Decision D3 Non-Linking Rule)
        SELECT con.convalidated,
               ARRAY(
                   SELECT a.attname::text
                     FROM unnest(con.conkey) AS k(attnum)
                     JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = k.attnum
                    ORDER BY a.attname
               ),
               regexp_replace(pg_get_expr(con.conbin, con.conrelid), '\s+', ' ', 'g')
          INTO v_chk_d3_val,
               v_chk_d3_cols,
               v_chk_d3_expr
          FROM pg_constraint con
         WHERE con.conrelid = v_lpmm_oid
           AND con.conname = 'chk_lpmm_probable_conflict_not_linked'
           AND con.contype = 'c';

        IF NOT FOUND THEN
            RAISE EXCEPTION
                'Schema verification failed: CHECK constraint chk_lpmm_probable_conflict_not_linked (Decision D3) is missing on public.legacy_profile_migration_map.';
        END IF;

        SELECT ARRAY(
                   SELECT m[1]
                     FROM regexp_matches(v_chk_d3_expr, '''([^'']+)''', 'g') WITH ORDINALITY AS t(m, ord)
                    ORDER BY t.ord
               )
          INTO v_chk_d3_lits;

        v_chk_d3_norm := btrim(
            regexp_replace(
                regexp_replace(
                    regexp_replace(v_chk_d3_expr, '::character varying(\[\])?|::varchar(\[\])?|::text(\[\])?', '', 'g'),
                    '[()]', '', 'g'
                ),
                '\s+', ' ', 'g'
            )
        );

        IF v_chk_d3_val IS DISTINCT FROM TRUE
           OR v_chk_d3_cols IS DISTINCT FROM ARRAY['mapped_individual_profile_id', 'mapped_public_user_id', 'migration_status']::text[]
           OR v_chk_d3_lits IS DISTINCT FROM ARRAY[
               'pending_audit',
               'unmatched_preserved',
               'conflict_pending_manual_review',
               'invalid_mobile_preserved'
           ]::text[]
           OR v_chk_d3_norm IS DISTINCT FROM
              'migration_status <> ALL ARRAY[''pending_audit'', ''unmatched_preserved'', ''conflict_pending_manual_review'', ''invalid_mobile_preserved''] OR mapped_public_user_id IS NULL AND mapped_individual_profile_id IS NULL'
           OR v_chk_d3_expr NOT LIKE '%OR ((mapped_public_user_id IS NULL) AND (mapped_individual_profile_id IS NULL))%' THEN
            RAISE EXCEPTION
                'Schema verification failed: chk_lpmm_probable_conflict_not_linked (Decision D3) failed complete structural verification (validated=%, cols=%, literals=%, normalized_expr=%, raw_expr=%).',
                v_chk_d3_val, v_chk_d3_cols, v_chk_d3_lits, v_chk_d3_norm, v_chk_d3_expr;
        END IF;

        -- Check 3: `chk_lpmm_linked_requires_targets`
        SELECT con.convalidated,
               ARRAY(
                   SELECT a.attname::text
                     FROM unnest(con.conkey) AS k(attnum)
                     JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = k.attnum
                    ORDER BY a.attname
               ),
               regexp_replace(pg_get_expr(con.conbin, con.conrelid), '\s+', ' ', 'g')
          INTO v_chk_link_val,
               v_chk_link_cols,
               v_chk_link_expr
          FROM pg_constraint con
         WHERE con.conrelid = v_lpmm_oid
           AND con.conname = 'chk_lpmm_linked_requires_targets'
           AND con.contype = 'c';

        IF NOT FOUND THEN
            RAISE EXCEPTION
                'Schema verification failed: CHECK constraint chk_lpmm_linked_requires_targets is missing on public.legacy_profile_migration_map.';
        END IF;

        SELECT ARRAY(
                   SELECT m[1]
                     FROM regexp_matches(v_chk_link_expr, '''([^'']+)''', 'g') WITH ORDINALITY AS t(m, ord)
                    ORDER BY t.ord
               )
          INTO v_chk_link_lits;

        v_chk_link_norm := btrim(
            regexp_replace(
                regexp_replace(
                    regexp_replace(v_chk_link_expr, '::character varying(\[\])?|::varchar(\[\])?|::text(\[\])?', '', 'g'),
                    '[()]', '', 'g'
                ),
                '\s+', ' ', 'g'
            )
        );

        IF v_chk_link_val IS DISTINCT FROM TRUE
           OR v_chk_link_cols IS DISTINCT FROM ARRAY['mapped_individual_profile_id', 'mapped_public_user_id', 'migration_status']::text[]
           OR v_chk_link_lits IS DISTINCT FROM ARRAY['linked_readonly']::text[]
           OR v_chk_link_norm IS DISTINCT FROM
              'migration_status <> ''linked_readonly'' OR mapped_public_user_id IS NOT NULL AND mapped_individual_profile_id IS NOT NULL'
           OR v_chk_link_expr NOT LIKE '%OR ((mapped_public_user_id IS NOT NULL) AND (mapped_individual_profile_id IS NOT NULL))%' THEN
            RAISE EXCEPTION
                'Schema verification failed: chk_lpmm_linked_requires_targets failed complete structural verification (validated=%, cols=%, literals=%, normalized_expr=%, raw_expr=%).',
                v_chk_link_val, v_chk_link_cols, v_chk_link_lits, v_chk_link_norm, v_chk_link_expr;
        END IF;

        -- Verify exact total constraint count (10 constraints: 1 PK, 2 UQ, 4 FK, 3 CHECK)
        SELECT COUNT(*)
          INTO v_total_cons
          FROM pg_constraint con
         WHERE con.conrelid = v_lpmm_oid;

        IF v_total_cons IS DISTINCT FROM 10 THEN
            RAISE EXCEPTION
                'Schema verification failed: pre-existing public.legacy_profile_migration_map has % constraints (expected exactly 10).',
                v_total_cons;
        END IF;
    END IF;
END $$;

-- -----------------------------------------------------------------------------
-- 4. Create or Structurally Verify Supporting Indexes on `legacy_profile_migration_map`
-- -----------------------------------------------------------------------------
DO $$
DECLARE
    v_idx_oid      OID;
    v_idx_schema   TEXT;
    v_table_schema TEXT;
    v_table_name   TEXT;
    v_relkind      "char";
    v_am_name      TEXT;
    v_is_unique    BOOLEAN;
    v_is_prim      BOOLEAN;
    v_is_valid     BOOLEAN;
    v_is_ready     BOOLEAN;
    v_is_live      BOOLEAN;
    v_natts        SMALLINT;
    v_nkeyatts     SMALLINT;
    v_has_exprs    BOOLEAN;
    v_key_cols     TEXT[];
    v_key_opts     INT4[];
    v_pred_expr    TEXT;
    v_idx_comment  TEXT;
BEGIN
    -- 4a. idx_lpmm_mapped_public_user_id
    SELECT i.oid,
           n.nspname,
           tn.nspname,
           t.relname,
           i.relkind,
           am.amname,
           ix.indisunique,
           ix.indisprimary,
           ix.indisvalid,
           ix.indisready,
           ix.indislive,
           ix.indnatts,
           ix.indnkeyatts,
           (ix.indexprs IS NOT NULL),
           ARRAY(
               SELECT a.attname::text
                 FROM unnest(ix.indkey::smallint[]) WITH ORDINALITY AS k(attnum, ord)
                 JOIN pg_attribute a ON a.attrelid = ix.indrelid AND a.attnum = k.attnum
                WHERE k.ord <= ix.indnkeyatts
                ORDER BY k.ord
           ),
           ARRAY(
               SELECT o.opt::int4
                 FROM unnest(ix.indoption::smallint[]) WITH ORDINALITY AS o(opt, ord)
                WHERE o.ord <= ix.indnkeyatts
                ORDER BY o.ord
           ),
           pg_get_expr(ix.indpred, ix.indrelid)
      INTO v_idx_oid,
           v_idx_schema,
           v_table_schema,
           v_table_name,
           v_relkind,
           v_am_name,
           v_is_unique,
           v_is_prim,
           v_is_valid,
           v_is_ready,
           v_is_live,
           v_natts,
           v_nkeyatts,
           v_has_exprs,
           v_key_cols,
           v_key_opts,
           v_pred_expr
      FROM pg_class i
      JOIN pg_namespace n ON n.oid = i.relnamespace
      LEFT JOIN pg_am am ON am.oid = i.relam
      LEFT JOIN pg_index ix ON ix.indexrelid = i.oid
      LEFT JOIN pg_class t ON t.oid = ix.indrelid
      LEFT JOIN pg_namespace tn ON tn.oid = t.relnamespace
     WHERE n.nspname = 'public'
       AND i.relname = 'idx_lpmm_mapped_public_user_id';

    IF NOT FOUND THEN
        CREATE INDEX idx_lpmm_mapped_public_user_id
            ON public.legacy_profile_migration_map (mapped_public_user_id)
            WHERE mapped_public_user_id IS NOT NULL;

        COMMENT ON INDEX public.idx_lpmm_mapped_public_user_id
            IS 'created_by_migration:014_job_seeker_conversion';
    ELSE
        IF v_idx_schema IS DISTINCT FROM 'public'
           OR v_relkind IS DISTINCT FROM 'i'
           OR v_table_schema IS DISTINCT FROM 'public'
           OR v_table_name IS DISTINCT FROM 'legacy_profile_migration_map'
           OR v_am_name IS DISTINCT FROM 'btree'
           OR v_is_unique IS DISTINCT FROM FALSE
           OR v_is_prim IS DISTINCT FROM FALSE
           OR v_is_valid IS DISTINCT FROM TRUE
           OR v_is_ready IS DISTINCT FROM TRUE
           OR v_is_live IS DISTINCT FROM TRUE
           OR v_natts IS DISTINCT FROM 1
           OR v_nkeyatts IS DISTINCT FROM 1
           OR v_has_exprs IS DISTINCT FROM FALSE
           OR v_key_cols IS DISTINCT FROM ARRAY['mapped_public_user_id']::text[]
           OR v_key_opts IS DISTINCT FROM ARRAY[0]::int4[]
           OR v_pred_expr IS DISTINCT FROM '(mapped_public_user_id IS NOT NULL)' THEN
            RAISE EXCEPTION
                'Schema verification failed: pre-existing idx_lpmm_mapped_public_user_id has structural mismatch (idx_schema=%, tbl_schema=%, table=%, am=%, unique=%, valid=%, ready=%, live=%, cols=%, opts=%, pred=%).',
                v_idx_schema, v_table_schema, v_table_name, v_am_name, v_is_unique,
                v_is_valid, v_is_ready, v_is_live, v_key_cols, v_key_opts, v_pred_expr;
        END IF;

        SELECT obj_description(v_idx_oid, 'pg_class')
          INTO v_idx_comment;

        IF v_idx_comment IS NOT NULL
           AND v_idx_comment IS DISTINCT FROM 'created_by_migration:014_job_seeker_conversion' THEN
            RAISE EXCEPTION
                'Schema verification failed: pre-existing idx_lpmm_mapped_public_user_id has conflicting catalog comment (%).',
                v_idx_comment;
        END IF;
    END IF;

    -- 4b. idx_lpmm_mapped_ind_profile_id
    SELECT i.oid,
           n.nspname,
           tn.nspname,
           t.relname,
           i.relkind,
           am.amname,
           ix.indisunique,
           ix.indisprimary,
           ix.indisvalid,
           ix.indisready,
           ix.indislive,
           ix.indnatts,
           ix.indnkeyatts,
           (ix.indexprs IS NOT NULL),
           ARRAY(
               SELECT a.attname::text
                 FROM unnest(ix.indkey::smallint[]) WITH ORDINALITY AS k(attnum, ord)
                 JOIN pg_attribute a ON a.attrelid = ix.indrelid AND a.attnum = k.attnum
                WHERE k.ord <= ix.indnkeyatts
                ORDER BY k.ord
           ),
           ARRAY(
               SELECT o.opt::int4
                 FROM unnest(ix.indoption::smallint[]) WITH ORDINALITY AS o(opt, ord)
                WHERE o.ord <= ix.indnkeyatts
                ORDER BY o.ord
           ),
           pg_get_expr(ix.indpred, ix.indrelid)
      INTO v_idx_oid,
           v_idx_schema,
           v_table_schema,
           v_table_name,
           v_relkind,
           v_am_name,
           v_is_unique,
           v_is_prim,
           v_is_valid,
           v_is_ready,
           v_is_live,
           v_natts,
           v_nkeyatts,
           v_has_exprs,
           v_key_cols,
           v_key_opts,
           v_pred_expr
      FROM pg_class i
      JOIN pg_namespace n ON n.oid = i.relnamespace
      LEFT JOIN pg_am am ON am.oid = i.relam
      LEFT JOIN pg_index ix ON ix.indexrelid = i.oid
      LEFT JOIN pg_class t ON t.oid = ix.indrelid
      LEFT JOIN pg_namespace tn ON tn.oid = t.relnamespace
     WHERE n.nspname = 'public'
       AND i.relname = 'idx_lpmm_mapped_ind_profile_id';

    IF NOT FOUND THEN
        CREATE INDEX idx_lpmm_mapped_ind_profile_id
            ON public.legacy_profile_migration_map (mapped_individual_profile_id)
            WHERE mapped_individual_profile_id IS NOT NULL;

        COMMENT ON INDEX public.idx_lpmm_mapped_ind_profile_id
            IS 'created_by_migration:014_job_seeker_conversion';
    ELSE
        IF v_idx_schema IS DISTINCT FROM 'public'
           OR v_relkind IS DISTINCT FROM 'i'
           OR v_table_schema IS DISTINCT FROM 'public'
           OR v_table_name IS DISTINCT FROM 'legacy_profile_migration_map'
           OR v_am_name IS DISTINCT FROM 'btree'
           OR v_is_unique IS DISTINCT FROM FALSE
           OR v_is_prim IS DISTINCT FROM FALSE
           OR v_is_valid IS DISTINCT FROM TRUE
           OR v_is_ready IS DISTINCT FROM TRUE
           OR v_is_live IS DISTINCT FROM TRUE
           OR v_natts IS DISTINCT FROM 1
           OR v_nkeyatts IS DISTINCT FROM 1
           OR v_has_exprs IS DISTINCT FROM FALSE
           OR v_key_cols IS DISTINCT FROM ARRAY['mapped_individual_profile_id']::text[]
           OR v_key_opts IS DISTINCT FROM ARRAY[0]::int4[]
           OR v_pred_expr IS DISTINCT FROM '(mapped_individual_profile_id IS NOT NULL)' THEN
            RAISE EXCEPTION
                'Schema verification failed: pre-existing idx_lpmm_mapped_ind_profile_id has structural mismatch (idx_schema=%, tbl_schema=%, table=%, am=%, unique=%, valid=%, ready=%, live=%, cols=%, opts=%, pred=%).',
                v_idx_schema, v_table_schema, v_table_name, v_am_name, v_is_unique,
                v_is_valid, v_is_ready, v_is_live, v_key_cols, v_key_opts, v_pred_expr;
        END IF;

        SELECT obj_description(v_idx_oid, 'pg_class')
          INTO v_idx_comment;

        IF v_idx_comment IS NOT NULL
           AND v_idx_comment IS DISTINCT FROM 'created_by_migration:014_job_seeker_conversion' THEN
            RAISE EXCEPTION
                'Schema verification failed: pre-existing idx_lpmm_mapped_ind_profile_id has conflicting catalog comment (%).',
                v_idx_comment;
        END IF;
    END IF;

    -- 4c. idx_lpmm_migration_status
    SELECT i.oid,
           n.nspname,
           tn.nspname,
           t.relname,
           i.relkind,
           am.amname,
           ix.indisunique,
           ix.indisprimary,
           ix.indisvalid,
           ix.indisready,
           ix.indislive,
           ix.indnatts,
           ix.indnkeyatts,
           (ix.indexprs IS NOT NULL),
           ARRAY(
               SELECT a.attname::text
                 FROM unnest(ix.indkey::smallint[]) WITH ORDINALITY AS k(attnum, ord)
                 JOIN pg_attribute a ON a.attrelid = ix.indrelid AND a.attnum = k.attnum
                WHERE k.ord <= ix.indnkeyatts
                ORDER BY k.ord
           ),
           ARRAY(
               SELECT o.opt::int4
                 FROM unnest(ix.indoption::smallint[]) WITH ORDINALITY AS o(opt, ord)
                WHERE o.ord <= ix.indnkeyatts
                ORDER BY o.ord
           ),
           pg_get_expr(ix.indpred, ix.indrelid)
      INTO v_idx_oid,
           v_idx_schema,
           v_table_schema,
           v_table_name,
           v_relkind,
           v_am_name,
           v_is_unique,
           v_is_prim,
           v_is_valid,
           v_is_ready,
           v_is_live,
           v_natts,
           v_nkeyatts,
           v_has_exprs,
           v_key_cols,
           v_key_opts,
           v_pred_expr
      FROM pg_class i
      JOIN pg_namespace n ON n.oid = i.relnamespace
      LEFT JOIN pg_am am ON am.oid = i.relam
      LEFT JOIN pg_index ix ON ix.indexrelid = i.oid
      LEFT JOIN pg_class t ON t.oid = ix.indrelid
      LEFT JOIN pg_namespace tn ON tn.oid = t.relnamespace
     WHERE n.nspname = 'public'
       AND i.relname = 'idx_lpmm_migration_status';

    IF NOT FOUND THEN
        CREATE INDEX idx_lpmm_migration_status
            ON public.legacy_profile_migration_map (migration_status);

        COMMENT ON INDEX public.idx_lpmm_migration_status
            IS 'created_by_migration:014_job_seeker_conversion';
    ELSE
        IF v_idx_schema IS DISTINCT FROM 'public'
           OR v_relkind IS DISTINCT FROM 'i'
           OR v_table_schema IS DISTINCT FROM 'public'
           OR v_table_name IS DISTINCT FROM 'legacy_profile_migration_map'
           OR v_am_name IS DISTINCT FROM 'btree'
           OR v_is_unique IS DISTINCT FROM FALSE
           OR v_is_prim IS DISTINCT FROM FALSE
           OR v_is_valid IS DISTINCT FROM TRUE
           OR v_is_ready IS DISTINCT FROM TRUE
           OR v_is_live IS DISTINCT FROM TRUE
           OR v_natts IS DISTINCT FROM 1
           OR v_nkeyatts IS DISTINCT FROM 1
           OR v_has_exprs IS DISTINCT FROM FALSE
           OR v_key_cols IS DISTINCT FROM ARRAY['migration_status']::text[]
           OR v_key_opts IS DISTINCT FROM ARRAY[0]::int4[]
           OR v_pred_expr IS NOT NULL THEN
            RAISE EXCEPTION
                'Schema verification failed: pre-existing idx_lpmm_migration_status has structural mismatch (idx_schema=%, tbl_schema=%, table=%, am=%, unique=%, valid=%, ready=%, live=%, cols=%, opts=%, pred=%).',
                v_idx_schema, v_table_schema, v_table_name, v_am_name, v_is_unique,
                v_is_valid, v_is_ready, v_is_live, v_key_cols, v_key_opts, v_pred_expr;
        END IF;

        SELECT obj_description(v_idx_oid, 'pg_class')
          INTO v_idx_comment;

        IF v_idx_comment IS NOT NULL
           AND v_idx_comment IS DISTINCT FROM 'created_by_migration:014_job_seeker_conversion' THEN
            RAISE EXCEPTION
                'Schema verification failed: pre-existing idx_lpmm_migration_status has conflicting catalog comment (%).',
                v_idx_comment;
        END IF;
    END IF;
END $$;

COMMIT;
