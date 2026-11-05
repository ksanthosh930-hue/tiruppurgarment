-- =============================================================================
-- Migration: 014_job_seeker_conversion_down.sql
-- Project:   DigiGarment – Job Seeker Registration & Conversion Optimization
-- Gate:      Prepared in Gate B / Corrected in Gate B.1, Gate B.2 & Gate B.3
--            (DO NOT EXECUTE unless Rollback is Explicitly Approved)
-- =============================================================================
--
-- CONSERVATIVE ATOMIC ROLLBACK SAFETY POLICY:
--   1. Executes atomically inside a single transaction (`BEGIN ... COMMIT`).
--      All ownership, structural definition, index state (`indisvalid`,
--      `indisready`, `indisunique`, `indislive`, `indisprimary`), constraint,
--      trigger, RLS policy, view/object dependency, and data-preservation
--      checks run in Phase 1 BEFORE any `DROP` operation executes in Phase 2.
--   2. NEVER uses `CASCADE` on any `DROP` statement (`RESTRICT` is used
--      explicitly on every `DROP INDEX`, `DROP TABLE`, and `DROP COLUMN`).
--   3. NEVER deletes or modifies records in `users`, `job_seeker_profiles`,
--      `public_users`, `individual_profiles`, `jobs`, or `job_applications`.
--   4. NEVER drops `idx_job_app_unique_candidate` (owned by migration 010).
--   5. Before considering any supporting index, unique index, column, or table
--      for removal, Phase 1 verifies:
--        a) Its explicit ownership marker (`created_by_migration:014_job_seeker_conversion`),
--        b) Its exact table schema (`tn.nspname = 'public'`), table association
--           (`t.relname`), and catalog index state (`indisvalid = TRUE`,
--           `indisready = TRUE`, `indisunique`, `indislive = TRUE`, `indisprimary = FALSE`),
--        c) Its structural catalog definition (`relkind = 'i'`, `amname = 'btree'`,
--           `indnatts`, `indnkeyatts`, `indprs IS NULL`, key column names,
--           key options, and exact partial predicate via `pg_get_expr(ix.indpred, ix.indrelid)`),
--        d) Zero unexpected indexes, triggers, RLS policies, inbound FKs, or
--           external dependencies in `pg_constraint` and `pg_depend` across
--           all catalog classes (`pg_rewrite` for views, `pg_trigger`, `pg_proc`,
--           `pg_constraint`, `pg_class`, etc.).
--   6. If any ownership check, index validity/readiness/liveness check,
--      structural definition check, row-count check, or dependency check is
--      uncertain or fails, rollback aborts immediately via `RAISE EXCEPTION`
--      and requires manual DBA review.
-- =============================================================================

BEGIN;

DO $$
DECLARE
    v_has_lpmm_table       BOOLEAN := FALSE;
    v_has_idx_pub_uid      BOOLEAN := FALSE;
    v_has_idx_ind_id       BOOLEAN := FALSE;
    v_has_idx_status       BOOLEAN := FALSE;
    v_has_event_id_col     BOOLEAN := FALSE;
    v_has_event_id_idx     BOOLEAN := FALSE;

    v_lpmm_oid             OID;
    v_lpmm_relkind         "char";
    v_lpmm_persist         "char";
    v_idx_pub_oid          OID;
    v_idx_ind_oid          OID;
    v_idx_stat_oid         OID;
    v_jae_oid              OID;
    v_jae_relkind          "char";
    v_jae_persist          "char";
    v_event_id_attnum      SMALLINT;
    v_event_idx_oid        OID;

    v_table_comment        TEXT;
    v_idx_pub_comment      TEXT;
    v_idx_ind_comment      TEXT;
    v_idx_stat_comment     TEXT;
    v_col_comment          TEXT;
    v_event_idx_comment    TEXT;

    -- Structural & state verification variables for indexes & column
    v_idx_tbl_schema       TEXT;
    v_idx_tbl_name         TEXT;
    v_idx_relkind          "char";
    v_idx_am_name          TEXT;
    v_idx_is_valid         BOOLEAN;
    v_idx_is_ready         BOOLEAN;
    v_idx_is_unique        BOOLEAN;
    v_idx_is_live          BOOLEAN;
    v_idx_is_prim          BOOLEAN;
    v_idx_natts            SMALLINT;
    v_idx_nkeyatts         SMALLINT;
    v_idx_has_exprs        BOOLEAN;
    v_idx_key_cols         TEXT[];
    v_idx_key_opts         INT4[];
    v_idx_pred_expr        TEXT;
    v_idx_ext_deps         BIGINT := 0;
    v_idx_ext_dep_detail   TEXT;

    v_col_data_type        TEXT;
    v_col_udt_name         TEXT;
    v_col_max_len          INTEGER;
    v_col_is_nullable      TEXT;
    v_col_default          TEXT;

    v_lpmm_inbound_fks     BIGINT := 0;
    v_lpmm_unexpected_cons BIGINT := 0;
    v_lpmm_unexpected_idxs BIGINT := 0;
    v_lpmm_user_triggers   BIGINT := 0;
    v_lpmm_rls_policies    BIGINT := 0;
    v_lpmm_ext_deps        BIGINT := 0;
    v_lpmm_ext_dep_detail  TEXT;

    v_event_inbound_fks    BIGINT := 0;
    v_event_table_cons     BIGINT := 0;
    v_event_col_ext_deps   BIGINT := 0;
    v_event_ext_dep_detail TEXT;

    v_map_row_count        BIGINT := 0;
    v_event_id_cnt         BIGINT := 0;
BEGIN
    -- =========================================================================
    -- PHASE 1: UPFRONT OWNERSHIP, STRUCTURAL, CONSTRAINT, PG_DEPEND & DATA CHECKS
    -- =========================================================================

    -- -------------------------------------------------------------------------
    -- 1A. Inspect `public.legacy_profile_migration_map`
    -- -------------------------------------------------------------------------
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

    v_has_lpmm_table := (v_lpmm_oid IS NOT NULL);

    IF v_has_lpmm_table THEN
        IF v_lpmm_relkind IS DISTINCT FROM 'r'
           OR v_lpmm_persist IS DISTINCT FROM 'p' THEN
            RAISE EXCEPTION
                'Rollback halted: public.legacy_profile_migration_map has unexpected relation kind or persistence (relkind=%, relpersistence=%). Manual DBA review required.',
                v_lpmm_relkind, v_lpmm_persist;
        END IF;

        -- Acquire exclusive lock before inspecting rows & dependencies
        EXECUTE 'LOCK TABLE public.legacy_profile_migration_map IN ACCESS EXCLUSIVE MODE';

        SELECT obj_description(v_lpmm_oid, 'pg_class')
          INTO v_table_comment;

        IF v_table_comment IS DISTINCT FROM 'created_by_migration:014_job_seeker_conversion' THEN
            RAISE EXCEPTION
                'Rollback halted: public.legacy_profile_migration_map is not marked as owned by migration 014 (comment=%). Pre-existing objects are never dropped. Manual DBA review required.',
                v_table_comment;
        END IF;

        -- Check 1: Foreign keys from ANY table referencing legacy_profile_migration_map
        SELECT COUNT(*)
          INTO v_lpmm_inbound_fks
          FROM pg_constraint con
         WHERE con.contype = 'f'
           AND con.confrelid = v_lpmm_oid;

        IF v_lpmm_inbound_fks > 0 THEN
            RAISE EXCEPTION
                'Rollback halted: % foreign key constraint(s) reference public.legacy_profile_migration_map. Manual DBA review required.',
                v_lpmm_inbound_fks;
        END IF;

        -- Check 2: Unexpected constraints on legacy_profile_migration_map outside the 10 migration-014 constraints
        SELECT COUNT(*)
          INTO v_lpmm_unexpected_cons
          FROM pg_constraint con
         WHERE con.conrelid = v_lpmm_oid
           AND con.conname NOT IN (
               'legacy_profile_migration_map_pkey',
               'lpmm_legacy_user_id_fkey',
               'lpmm_legacy_jsp_id_fkey',
               'lpmm_mapped_public_user_id_fkey',
               'lpmm_mapped_individual_profile_id_fkey',
               'uq_lpmm_legacy_jsp_id',
               'uq_lpmm_legacy_user_id',
               'chk_lpmm_migration_status',
               'chk_lpmm_probable_conflict_not_linked',
               'chk_lpmm_linked_requires_targets'
           );

        IF v_lpmm_unexpected_cons > 0 THEN
            RAISE EXCEPTION
                'Rollback halted: public.legacy_profile_migration_map has % unexpected constraint(s). Manual DBA review required.',
                v_lpmm_unexpected_cons;
        END IF;

        -- Check 3: Unexpected indexes on legacy_profile_migration_map outside the 6 migration-014 indexes
        SELECT COUNT(*)
          INTO v_lpmm_unexpected_idxs
          FROM pg_index ix
          JOIN pg_class i ON i.oid = ix.indexrelid
         WHERE ix.indrelid = v_lpmm_oid
           AND i.relname NOT IN (
               'legacy_profile_migration_map_pkey',
               'uq_lpmm_legacy_jsp_id',
               'uq_lpmm_legacy_user_id',
               'idx_lpmm_mapped_public_user_id',
               'idx_lpmm_mapped_ind_profile_id',
               'idx_lpmm_migration_status'
           );

        IF v_lpmm_unexpected_idxs > 0 THEN
            RAISE EXCEPTION
                'Rollback halted: public.legacy_profile_migration_map has % unexpected index(es). Manual DBA review required.',
                v_lpmm_unexpected_idxs;
        END IF;

        -- Check 4: User triggers or RLS policies on legacy_profile_migration_map
        SELECT COUNT(*)
          INTO v_lpmm_user_triggers
          FROM pg_trigger tg
         WHERE tg.tgrelid = v_lpmm_oid
           AND NOT tg.tgisinternal;

        IF v_lpmm_user_triggers > 0 THEN
            RAISE EXCEPTION
                'Rollback halted: public.legacy_profile_migration_map has % non-internal trigger(s). Manual DBA review required.',
                v_lpmm_user_triggers;
        END IF;

        SELECT COUNT(*)
          INTO v_lpmm_rls_policies
          FROM pg_policy pol
         WHERE pol.polrelid = v_lpmm_oid;

        IF v_lpmm_rls_policies > 0 THEN
            RAISE EXCEPTION
                'Rollback halted: public.legacy_profile_migration_map has % RLS policy/policies. Manual DBA review required.',
                v_lpmm_rls_policies;
        END IF;

        -- Check 5: Comprehensive pg_depend check across ALL catalog classes
        SELECT COUNT(*),
               string_agg(pg_describe_object(d.classid, d.objid, d.objsubid), '; ')
          INTO v_lpmm_ext_deps,
               v_lpmm_ext_dep_detail
          FROM pg_depend d
         WHERE d.refclassid = 'pg_class'::regclass
           AND d.refobjid = v_lpmm_oid
           AND NOT (
               (d.classid = 'pg_class'::regclass AND d.objid = v_lpmm_oid)
               OR (
                   d.classid = 'pg_class'::regclass
                   AND d.objid = (
                       SELECT c.reltoastrelid
                         FROM pg_class c
                        WHERE c.oid = v_lpmm_oid
                          AND c.reltoastrelid <> 0
                   )
               )
               OR (
                   d.classid = 'pg_type'::regclass
                   AND d.objid IN (
                       SELECT t.oid FROM pg_type t WHERE t.typrelid = v_lpmm_oid
                       UNION
                       SELECT t.typarray FROM pg_type t WHERE t.typrelid = v_lpmm_oid AND t.typarray <> 0
                   )
               )
               OR (
                   d.classid = 'pg_class'::regclass
                   AND d.objid IN (
                       SELECT c.oid
                         FROM pg_class c
                         JOIN pg_namespace n ON n.oid = c.relnamespace
                        WHERE n.nspname = 'public'
                          AND c.relkind = 'S'
                          AND c.relname = 'legacy_profile_migration_map_id_seq'
                   )
               )
               OR (
                   d.classid = 'pg_attrdef'::regclass
                   AND d.objid IN (
                       SELECT ad.oid FROM pg_attrdef ad WHERE ad.adrelid = v_lpmm_oid
                   )
               )
               OR (
                   d.classid = 'pg_constraint'::regclass
                   AND d.objid IN (
                       SELECT con.oid
                         FROM pg_constraint con
                        WHERE con.conrelid = v_lpmm_oid
                          AND con.conname IN (
                              'legacy_profile_migration_map_pkey',
                              'lpmm_legacy_user_id_fkey',
                              'lpmm_legacy_jsp_id_fkey',
                              'lpmm_mapped_public_user_id_fkey',
                              'lpmm_mapped_individual_profile_id_fkey',
                              'uq_lpmm_legacy_jsp_id',
                              'uq_lpmm_legacy_user_id',
                              'chk_lpmm_migration_status',
                              'chk_lpmm_probable_conflict_not_linked',
                              'chk_lpmm_linked_requires_targets'
                          )
                   )
               )
               OR (
                   d.classid = 'pg_class'::regclass
                   AND d.objid IN (
                       SELECT i.oid
                         FROM pg_index ix
                         JOIN pg_class i ON i.oid = ix.indexrelid
                        WHERE ix.indrelid = v_lpmm_oid
                          AND i.relname IN (
                              'legacy_profile_migration_map_pkey',
                              'uq_lpmm_legacy_jsp_id',
                              'uq_lpmm_legacy_user_id',
                              'idx_lpmm_mapped_public_user_id',
                              'idx_lpmm_mapped_ind_profile_id',
                              'idx_lpmm_migration_status'
                          )
                   )
               )
           );

        IF v_lpmm_ext_deps > 0 THEN
            RAISE EXCEPTION
                'Rollback halted: public.legacy_profile_migration_map has % dependent database object(s) (%). Manual DBA review required.',
                v_lpmm_ext_deps, v_lpmm_ext_dep_detail;
        END IF;

        -- Check 6: Non-empty table check
        EXECUTE 'SELECT COUNT(*) FROM public.legacy_profile_migration_map'
           INTO v_map_row_count;

        IF v_map_row_count > 0 THEN
            RAISE EXCEPTION
                'Rollback halted for data safety: public.legacy_profile_migration_map contains % row(s). Non-empty mapping tables are never dropped. Manual DBA review required.',
                v_map_row_count;
        END IF;
    END IF;

    -- -------------------------------------------------------------------------
    -- 1B. Inspect Supporting Index 1: `idx_lpmm_mapped_public_user_id`
    --     (Ownership + Table Schema/Association + indisvalid/indisready/indisunique/indislive
    --      + Structural Definition + pg_depend)
    -- -------------------------------------------------------------------------
    SELECT i.oid,
           tn.nspname,
           t.relname,
           i.relkind,
           am.amname,
           ix.indisvalid,
           ix.indisready,
           ix.indisunique,
           ix.indislive,
           ix.indisprimary,
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
      INTO v_idx_pub_oid,
           v_idx_tbl_schema,
           v_idx_tbl_name,
           v_idx_relkind,
           v_idx_am_name,
           v_idx_is_valid,
           v_idx_is_ready,
           v_idx_is_unique,
           v_idx_is_live,
           v_idx_is_prim,
           v_idx_natts,
           v_idx_nkeyatts,
           v_idx_has_exprs,
           v_idx_key_cols,
           v_idx_key_opts,
           v_idx_pred_expr
      FROM pg_class i
      JOIN pg_namespace n ON n.oid = i.relnamespace
      LEFT JOIN pg_am am ON am.oid = i.relam
      LEFT JOIN pg_index ix ON ix.indexrelid = i.oid
      LEFT JOIN pg_class t ON t.oid = ix.indrelid
      LEFT JOIN pg_namespace tn ON tn.oid = t.relnamespace
     WHERE n.nspname = 'public'
       AND i.relname = 'idx_lpmm_mapped_public_user_id';

    v_has_idx_pub_uid := (v_idx_pub_oid IS NOT NULL);

    IF v_has_idx_pub_uid THEN
        SELECT obj_description(v_idx_pub_oid, 'pg_class')
          INTO v_idx_pub_comment;

        IF v_idx_pub_comment IS DISTINCT FROM 'created_by_migration:014_job_seeker_conversion' THEN
            RAISE EXCEPTION
                'Rollback halted: idx_lpmm_mapped_public_user_id is not marked as owned by migration 014 (comment=%). Manual DBA review required.',
                v_idx_pub_comment;
        END IF;

        IF v_idx_relkind IS DISTINCT FROM 'i'
           OR v_idx_tbl_schema IS DISTINCT FROM 'public'
           OR v_idx_tbl_name IS DISTINCT FROM 'legacy_profile_migration_map'
           OR v_idx_am_name IS DISTINCT FROM 'btree'
           OR v_idx_is_valid IS DISTINCT FROM TRUE
           OR v_idx_is_ready IS DISTINCT FROM TRUE
           OR v_idx_is_unique IS DISTINCT FROM FALSE
           OR v_idx_is_live IS DISTINCT FROM TRUE
           OR v_idx_is_prim IS DISTINCT FROM FALSE
           OR v_idx_natts IS DISTINCT FROM 1
           OR v_idx_nkeyatts IS DISTINCT FROM 1
           OR v_idx_has_exprs IS DISTINCT FROM FALSE
           OR v_idx_key_cols IS DISTINCT FROM ARRAY['mapped_public_user_id']::text[]
           OR v_idx_key_opts IS DISTINCT FROM ARRAY[0]::int4[]
           OR v_idx_pred_expr IS DISTINCT FROM '(mapped_public_user_id IS NOT NULL)' THEN
            RAISE EXCEPTION
                'Rollback halted: idx_lpmm_mapped_public_user_id failed table schema/association (schema=%, table=%), state (indisvalid=%, indisready=%, indisunique=%, indislive=%), or structural verification (relkind=%, am=%, primary=%, cols=%, opts=%, pred=%). Manual DBA review required.',
                v_idx_tbl_schema, v_idx_tbl_name,
                v_idx_is_valid, v_idx_is_ready, v_idx_is_unique, v_idx_is_live,
                v_idx_relkind, v_idx_am_name, v_idx_is_prim,
                v_idx_key_cols, v_idx_key_opts, v_idx_pred_expr;
        END IF;

        SELECT COUNT(*),
               string_agg(pg_describe_object(d.classid, d.objid, d.objsubid), '; ')
          INTO v_idx_ext_deps,
               v_idx_ext_dep_detail
          FROM pg_depend d
         WHERE d.refclassid = 'pg_class'::regclass
           AND d.refobjid = v_idx_pub_oid
           AND NOT (d.classid = 'pg_class'::regclass AND d.objid = v_idx_pub_oid);

        IF v_idx_ext_deps > 0 THEN
            RAISE EXCEPTION
                'Rollback halted: idx_lpmm_mapped_public_user_id has % dependent object(s) (%). Manual DBA review required.',
                v_idx_ext_deps, v_idx_ext_dep_detail;
        END IF;
    END IF;

    -- -------------------------------------------------------------------------
    -- 1C. Inspect Supporting Index 2: `idx_lpmm_mapped_ind_profile_id`
    --     (Ownership + Table Schema/Association + indisvalid/indisready/indisunique/indislive
    --      + Structural Definition + pg_depend)
    -- -------------------------------------------------------------------------
    SELECT i.oid,
           tn.nspname,
           t.relname,
           i.relkind,
           am.amname,
           ix.indisvalid,
           ix.indisready,
           ix.indisunique,
           ix.indislive,
           ix.indisprimary,
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
      INTO v_idx_ind_oid,
           v_idx_tbl_schema,
           v_idx_tbl_name,
           v_idx_relkind,
           v_idx_am_name,
           v_idx_is_valid,
           v_idx_is_ready,
           v_idx_is_unique,
           v_idx_is_live,
           v_idx_is_prim,
           v_idx_natts,
           v_idx_nkeyatts,
           v_idx_has_exprs,
           v_idx_key_cols,
           v_idx_key_opts,
           v_idx_pred_expr
      FROM pg_class i
      JOIN pg_namespace n ON n.oid = i.relnamespace
      LEFT JOIN pg_am am ON am.oid = i.relam
      LEFT JOIN pg_index ix ON ix.indexrelid = i.oid
      LEFT JOIN pg_class t ON t.oid = ix.indrelid
      LEFT JOIN pg_namespace tn ON tn.oid = t.relnamespace
     WHERE n.nspname = 'public'
       AND i.relname = 'idx_lpmm_mapped_ind_profile_id';

    v_has_idx_ind_id := (v_idx_ind_oid IS NOT NULL);

    IF v_has_idx_ind_id THEN
        SELECT obj_description(v_idx_ind_oid, 'pg_class')
          INTO v_idx_ind_comment;

        IF v_idx_ind_comment IS DISTINCT FROM 'created_by_migration:014_job_seeker_conversion' THEN
            RAISE EXCEPTION
                'Rollback halted: idx_lpmm_mapped_ind_profile_id is not marked as owned by migration 014 (comment=%). Manual DBA review required.',
                v_idx_ind_comment;
        END IF;

        IF v_idx_relkind IS DISTINCT FROM 'i'
           OR v_idx_tbl_schema IS DISTINCT FROM 'public'
           OR v_idx_tbl_name IS DISTINCT FROM 'legacy_profile_migration_map'
           OR v_idx_am_name IS DISTINCT FROM 'btree'
           OR v_idx_is_valid IS DISTINCT FROM TRUE
           OR v_idx_is_ready IS DISTINCT FROM TRUE
           OR v_idx_is_unique IS DISTINCT FROM FALSE
           OR v_idx_is_live IS DISTINCT FROM TRUE
           OR v_idx_is_prim IS DISTINCT FROM FALSE
           OR v_idx_natts IS DISTINCT FROM 1
           OR v_idx_nkeyatts IS DISTINCT FROM 1
           OR v_idx_has_exprs IS DISTINCT FROM FALSE
           OR v_idx_key_cols IS DISTINCT FROM ARRAY['mapped_individual_profile_id']::text[]
           OR v_idx_key_opts IS DISTINCT FROM ARRAY[0]::int4[]
           OR v_idx_pred_expr IS DISTINCT FROM '(mapped_individual_profile_id IS NOT NULL)' THEN
            RAISE EXCEPTION
                'Rollback halted: idx_lpmm_mapped_ind_profile_id failed table schema/association (schema=%, table=%), state (indisvalid=%, indisready=%, indisunique=%, indislive=%), or structural verification (relkind=%, am=%, primary=%, cols=%, opts=%, pred=%). Manual DBA review required.',
                v_idx_tbl_schema, v_idx_tbl_name,
                v_idx_is_valid, v_idx_is_ready, v_idx_is_unique, v_idx_is_live,
                v_idx_relkind, v_idx_am_name, v_idx_is_prim,
                v_idx_key_cols, v_idx_key_opts, v_idx_pred_expr;
        END IF;

        SELECT COUNT(*),
               string_agg(pg_describe_object(d.classid, d.objid, d.objsubid), '; ')
          INTO v_idx_ext_deps,
               v_idx_ext_dep_detail
          FROM pg_depend d
         WHERE d.refclassid = 'pg_class'::regclass
           AND d.refobjid = v_idx_ind_oid
           AND NOT (d.classid = 'pg_class'::regclass AND d.objid = v_idx_ind_oid);

        IF v_idx_ext_deps > 0 THEN
            RAISE EXCEPTION
                'Rollback halted: idx_lpmm_mapped_ind_profile_id has % dependent object(s) (%). Manual DBA review required.',
                v_idx_ext_deps, v_idx_ext_dep_detail;
        END IF;
    END IF;

    -- -------------------------------------------------------------------------
    -- 1D. Inspect Supporting Index 3: `idx_lpmm_migration_status`
    --     (Ownership + Table Schema/Association + indisvalid/indisready/indisunique/indislive
    --      + Structural Definition + pg_depend)
    -- -------------------------------------------------------------------------
    SELECT i.oid,
           tn.nspname,
           t.relname,
           i.relkind,
           am.amname,
           ix.indisvalid,
           ix.indisready,
           ix.indisunique,
           ix.indislive,
           ix.indisprimary,
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
      INTO v_idx_stat_oid,
           v_idx_tbl_schema,
           v_idx_tbl_name,
           v_idx_relkind,
           v_idx_am_name,
           v_idx_is_valid,
           v_idx_is_ready,
           v_idx_is_unique,
           v_idx_is_live,
           v_idx_is_prim,
           v_idx_natts,
           v_idx_nkeyatts,
           v_idx_has_exprs,
           v_idx_key_cols,
           v_idx_key_opts,
           v_idx_pred_expr
      FROM pg_class i
      JOIN pg_namespace n ON n.oid = i.relnamespace
      LEFT JOIN pg_am am ON am.oid = i.relam
      LEFT JOIN pg_index ix ON ix.indexrelid = i.oid
      LEFT JOIN pg_class t ON t.oid = ix.indrelid
      LEFT JOIN pg_namespace tn ON tn.oid = t.relnamespace
     WHERE n.nspname = 'public'
       AND i.relname = 'idx_lpmm_migration_status';

    v_has_idx_status := (v_idx_stat_oid IS NOT NULL);

    IF v_has_idx_status THEN
        SELECT obj_description(v_idx_stat_oid, 'pg_class')
          INTO v_idx_stat_comment;

        IF v_idx_stat_comment IS DISTINCT FROM 'created_by_migration:014_job_seeker_conversion' THEN
            RAISE EXCEPTION
                'Rollback halted: idx_lpmm_migration_status is not marked as owned by migration 014 (comment=%). Manual DBA review required.',
                v_idx_stat_comment;
        END IF;

        IF v_idx_relkind IS DISTINCT FROM 'i'
           OR v_idx_tbl_schema IS DISTINCT FROM 'public'
           OR v_idx_tbl_name IS DISTINCT FROM 'legacy_profile_migration_map'
           OR v_idx_am_name IS DISTINCT FROM 'btree'
           OR v_idx_is_valid IS DISTINCT FROM TRUE
           OR v_idx_is_ready IS DISTINCT FROM TRUE
           OR v_idx_is_unique IS DISTINCT FROM FALSE
           OR v_idx_is_live IS DISTINCT FROM TRUE
           OR v_idx_is_prim IS DISTINCT FROM FALSE
           OR v_idx_natts IS DISTINCT FROM 1
           OR v_idx_nkeyatts IS DISTINCT FROM 1
           OR v_idx_has_exprs IS DISTINCT FROM FALSE
           OR v_idx_key_cols IS DISTINCT FROM ARRAY['migration_status']::text[]
           OR v_idx_key_opts IS DISTINCT FROM ARRAY[0]::int4[]
           OR v_idx_pred_expr IS NOT NULL THEN
            RAISE EXCEPTION
                'Rollback halted: idx_lpmm_migration_status failed table schema/association (schema=%, table=%), state (indisvalid=%, indisready=%, indisunique=%, indislive=%), or structural verification (relkind=%, am=%, primary=%, cols=%, opts=%, pred=%). Manual DBA review required.',
                v_idx_tbl_schema, v_idx_tbl_name,
                v_idx_is_valid, v_idx_is_ready, v_idx_is_unique, v_idx_is_live,
                v_idx_relkind, v_idx_am_name, v_idx_is_prim,
                v_idx_key_cols, v_idx_key_opts, v_idx_pred_expr;
        END IF;

        SELECT COUNT(*),
               string_agg(pg_describe_object(d.classid, d.objid, d.objsubid), '; ')
          INTO v_idx_ext_deps,
               v_idx_ext_dep_detail
          FROM pg_depend d
         WHERE d.refclassid = 'pg_class'::regclass
           AND d.refobjid = v_idx_stat_oid
           AND NOT (d.classid = 'pg_class'::regclass AND d.objid = v_idx_stat_oid);

        IF v_idx_ext_deps > 0 THEN
            RAISE EXCEPTION
                'Rollback halted: idx_lpmm_migration_status has % dependent object(s) (%). Manual DBA review required.',
                v_idx_ext_deps, v_idx_ext_dep_detail;
        END IF;
    END IF;

    -- -------------------------------------------------------------------------
    -- 1E. Inspect `idx_job_analytics_events_event_id_unique` & `event_id` column
    --     (Ownership + Table Schema/Association + indisvalid/indisready/indisunique/indislive
    --      + Structural Definition + pg_depend)
    -- -------------------------------------------------------------------------
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
            'Rollback halted: public.job_analytics_events must exist as an ordinary permanent table (relkind=%, relpersistence=%). Manual DBA review required.',
            v_jae_relkind, v_jae_persist;
    END IF;

    SELECT a.attnum
      INTO v_event_id_attnum
      FROM pg_attribute a
     WHERE a.attrelid = v_jae_oid
       AND a.attname = 'event_id'
       AND NOT a.attisdropped;

    v_has_event_id_col := (v_event_id_attnum IS NOT NULL);

    SELECT i.oid,
           tn.nspname,
           t.relname,
           i.relkind,
           am.amname,
           ix.indisvalid,
           ix.indisready,
           ix.indisunique,
           ix.indislive,
           ix.indisprimary,
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
      INTO v_event_idx_oid,
           v_idx_tbl_schema,
           v_idx_tbl_name,
           v_idx_relkind,
           v_idx_am_name,
           v_idx_is_valid,
           v_idx_is_ready,
           v_idx_is_unique,
           v_idx_is_live,
           v_idx_is_prim,
           v_idx_natts,
           v_idx_nkeyatts,
           v_idx_has_exprs,
           v_idx_key_cols,
           v_idx_key_opts,
           v_idx_pred_expr
      FROM pg_class i
      JOIN pg_namespace n ON n.oid = i.relnamespace
      LEFT JOIN pg_am am ON am.oid = i.relam
      LEFT JOIN pg_index ix ON ix.indexrelid = i.oid
      LEFT JOIN pg_class t ON t.oid = ix.indrelid
      LEFT JOIN pg_namespace tn ON tn.oid = t.relnamespace
     WHERE n.nspname = 'public'
       AND i.relname = 'idx_job_analytics_events_event_id_unique';

    v_has_event_id_idx := (v_event_idx_oid IS NOT NULL);

    IF v_has_event_id_col OR v_has_event_id_idx THEN
        EXECUTE 'LOCK TABLE public.job_analytics_events IN ACCESS EXCLUSIVE MODE';
    END IF;

    IF v_has_event_id_idx THEN
        SELECT obj_description(v_event_idx_oid, 'pg_class')
          INTO v_event_idx_comment;

        IF v_event_idx_comment IS DISTINCT FROM 'created_by_migration:014_job_seeker_conversion' THEN
            RAISE EXCEPTION
                'Rollback halted: idx_job_analytics_events_event_id_unique is not marked as owned by migration 014 (comment=%). Pre-existing indexes are never dropped. Manual DBA review required.',
                v_event_idx_comment;
        END IF;

        IF v_idx_relkind IS DISTINCT FROM 'i'
           OR v_idx_tbl_schema IS DISTINCT FROM 'public'
           OR v_idx_tbl_name IS DISTINCT FROM 'job_analytics_events'
           OR v_idx_am_name IS DISTINCT FROM 'btree'
           OR v_idx_is_valid IS DISTINCT FROM TRUE
           OR v_idx_is_ready IS DISTINCT FROM TRUE
           OR v_idx_is_unique IS DISTINCT FROM TRUE
           OR v_idx_is_live IS DISTINCT FROM TRUE
           OR v_idx_is_prim IS DISTINCT FROM FALSE
           OR v_idx_natts IS DISTINCT FROM 1
           OR v_idx_nkeyatts IS DISTINCT FROM 1
           OR v_idx_has_exprs IS DISTINCT FROM FALSE
           OR v_idx_key_cols IS DISTINCT FROM ARRAY['event_id']::text[]
           OR v_idx_key_opts IS DISTINCT FROM ARRAY[0]::int4[]
           OR v_idx_pred_expr IS DISTINCT FROM '(event_id IS NOT NULL)' THEN
            RAISE EXCEPTION
                'Rollback halted: idx_job_analytics_events_event_id_unique failed table schema/association (schema=%, table=%), state (indisvalid=%, indisready=%, indisunique=%, indislive=%), or structural verification (relkind=%, am=%, primary=%, cols=%, opts=%, pred=%). Manual DBA review required.',
                v_idx_tbl_schema, v_idx_tbl_name,
                v_idx_is_valid, v_idx_is_ready, v_idx_is_unique, v_idx_is_live,
                v_idx_relkind, v_idx_am_name, v_idx_is_prim,
                v_idx_key_cols, v_idx_key_opts, v_idx_pred_expr;
        END IF;

        SELECT COUNT(*),
               string_agg(pg_describe_object(d.classid, d.objid, d.objsubid), '; ')
          INTO v_idx_ext_deps,
               v_idx_ext_dep_detail
          FROM pg_depend d
         WHERE d.refclassid = 'pg_class'::regclass
           AND d.refobjid = v_event_idx_oid
           AND NOT (d.classid = 'pg_class'::regclass AND d.objid = v_event_idx_oid);

        IF v_idx_ext_deps > 0 THEN
            RAISE EXCEPTION
                'Rollback halted: idx_job_analytics_events_event_id_unique has % dependent object(s) (%). Manual DBA review required.',
                v_idx_ext_deps, v_idx_ext_dep_detail;
        END IF;
    END IF;

    IF v_has_event_id_col THEN
        SELECT col_description(v_jae_oid, v_event_id_attnum)
          INTO v_col_comment;

        IF v_col_comment IS DISTINCT FROM 'created_by_migration:014_job_seeker_conversion' THEN
            RAISE EXCEPTION
                'Rollback halted: public.job_analytics_events.event_id is not marked as owned by migration 014 (comment=%). Pre-existing columns are never dropped. Manual DBA review required.',
                v_col_comment;
        END IF;

        -- Verify structural column definition before dropping
        SELECT c.data_type,
               c.udt_name,
               c.character_maximum_length,
               c.is_nullable,
               c.column_default
          INTO v_col_data_type,
               v_col_udt_name,
               v_col_max_len,
               v_col_is_nullable,
               v_col_default
          FROM information_schema.columns c
         WHERE c.table_schema = 'public'
           AND c.table_name = 'job_analytics_events'
           AND c.column_name = 'event_id';

        IF v_col_data_type IS DISTINCT FROM 'character varying'
           OR v_col_udt_name IS DISTINCT FROM 'varchar'
           OR v_col_max_len IS DISTINCT FROM 128
           OR v_col_is_nullable IS DISTINCT FROM 'YES'
           OR v_col_default IS NOT NULL THEN
            RAISE EXCEPTION
                'Rollback halted: public.job_analytics_events.event_id failed structural verification (type=%, udt=%, len=%, nullable=%, default=%). Manual DBA review required.',
                v_col_data_type, v_col_udt_name, v_col_max_len, v_col_is_nullable, v_col_default;
        END IF;

        -- Check 1: Foreign keys from any table referencing job_analytics_events(event_id)
        SELECT COUNT(*)
          INTO v_event_inbound_fks
          FROM pg_constraint con
         WHERE con.contype = 'f'
           AND con.confrelid = v_jae_oid
           AND v_event_id_attnum = ANY(con.confkey);

        IF v_event_inbound_fks > 0 THEN
            RAISE EXCEPTION
                'Rollback halted: % foreign key constraint(s) reference public.job_analytics_events(event_id). Manual DBA review required.',
                v_event_inbound_fks;
        END IF;

        -- Check 2: Any table constraint on job_analytics_events involving event_id
        SELECT COUNT(*)
          INTO v_event_table_cons
          FROM pg_constraint con
         WHERE con.conrelid = v_jae_oid
           AND v_event_id_attnum = ANY(con.conkey);

        IF v_event_table_cons > 0 THEN
            RAISE EXCEPTION
                'Rollback halted: % constraint(s) on public.job_analytics_events reference column event_id. Manual DBA review required.',
                v_event_table_cons;
        END IF;

        -- Check 3: Comprehensive pg_depend check on job_analytics_events.event_id across ALL catalog classes
        SELECT COUNT(*),
               string_agg(pg_describe_object(d.classid, d.objid, d.objsubid), '; ')
          INTO v_event_col_ext_deps,
               v_event_ext_dep_detail
          FROM pg_depend d
         WHERE d.refclassid = 'pg_class'::regclass
           AND d.refobjid = v_jae_oid
           AND d.refobjsubid = v_event_id_attnum
           AND NOT (
               v_event_idx_oid IS NOT NULL
               AND d.classid = 'pg_class'::regclass
               AND d.objid = v_event_idx_oid
           );

        IF v_event_col_ext_deps > 0 THEN
            RAISE EXCEPTION
                'Rollback halted: public.job_analytics_events.event_id has % dependent object(s) (%). Manual DBA review required.',
                v_event_col_ext_deps, v_event_ext_dep_detail;
        END IF;

        -- Check 4: Populated event_id check
        EXECUTE 'SELECT COUNT(*) FROM public.job_analytics_events WHERE event_id IS NOT NULL'
           INTO v_event_id_cnt;

        IF v_event_id_cnt > 0 THEN
            RAISE EXCEPTION
                'Rollback halted for data safety: public.job_analytics_events contains % row(s) with non-NULL event_id values. Populated event_id columns and their unique index are never dropped. Manual DBA review required.',
                v_event_id_cnt;
        END IF;
    END IF;

    -- =========================================================================
    -- PHASE 2: ATOMIC REMOVAL OF VERIFIED MIGRATION-014-OWNED OBJECTS (RESTRICT)
    -- =========================================================================

    IF v_has_idx_pub_uid THEN
        DROP INDEX public.idx_lpmm_mapped_public_user_id RESTRICT;
    END IF;

    IF v_has_idx_ind_id THEN
        DROP INDEX public.idx_lpmm_mapped_ind_profile_id RESTRICT;
    END IF;

    IF v_has_idx_status THEN
        DROP INDEX public.idx_lpmm_migration_status RESTRICT;
    END IF;

    IF v_has_lpmm_table THEN
        DROP TABLE public.legacy_profile_migration_map RESTRICT;
    END IF;

    IF v_has_event_id_idx THEN
        DROP INDEX public.idx_job_analytics_events_event_id_unique RESTRICT;
    END IF;

    IF v_has_event_id_col THEN
        ALTER TABLE public.job_analytics_events
            DROP COLUMN event_id RESTRICT;
    END IF;
END $$;

COMMIT;
