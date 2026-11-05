"""
DigiGarment Legacy Profile Read-Only Audit Script
=================================================
Prepared in Gate B / Corrected in Gate B.1
(Preparation Only – DO NOT EXECUTE without authorization).

Safety Guarantees:
  1. Connects strictly in PostgreSQL READ ONLY mode (`readonly=True`, `SET TRANSACTION READ ONLY`).
  2. Contains ZERO write capability: never executes INSERT, UPDATE, DELETE, ALTER, CREATE, or DROP.
  3. Never modifies or merges `users`, `job_seeker_profiles`, `public_users`, or `individual_profiles`.
  4. Explicitly verifies relational integrity before proposing any `1_exact_match`:
       - `individual_profiles.user_id` must exist in `public_users.id` (`1:1` unique linkage).
       - Proposed `public_users` record must have `account_type == 'individual'` and `is_active == True`.
       - Proposed `public_users.id` and normalized mobile must not appear in `company_profiles`.
       - Legacy `job_seeker_profiles.user_id` must map `1:1` to an active synthetic candidate
         record (`@candidate.digigarment.local`) in `users`.
  5. Enforces Decision D3: probable matches (`2_probable_match`) remain strictly unlinked
     (`proposed_migration_status = 'conflict_pending_manual_review'`,
     `proposed_mapped_public_user_id = None`, `proposed_mapped_individual_profile_id = None`).
  6. Masks all PII (mobile numbers, emails, and names) in memory before any output is produced.
"""

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Set

import psycopg2
from dotenv import load_dotenv


def normalize_indian_mobile(raw_value: Optional[str]) -> str:
    """Normalize a raw phone string to digits, stripping +91 or leading 0 where applicable."""
    digits = re.sub(r"\D", "", str(raw_value or ""))
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    return digits


def is_valid_indian_mobile(norm_digits: str) -> bool:
    """Return True if norm_digits is a valid 10-digit Indian mobile number."""
    return bool(re.match(r"^[6-9]\d{9}$", norm_digits))


def mask_mobile(raw_value: Optional[str]) -> str:
    """Mask mobile number so raw PII is never displayed."""
    norm = normalize_indian_mobile(raw_value)
    if len(norm) >= 4:
        return f"XXXXXX{norm[-4:]}"
    return "INVALID_OR_EMPTY"


def normalize_name(raw_name: Optional[str]) -> str:
    """Normalize name string for comparison without exposing it."""
    return re.sub(r"\s+", " ", str(raw_name or "").strip().lower())


def run_readonly_audit(include_masked_proposals: bool = False) -> Dict[str, Any]:
    """Execute the 6-category legacy profile audit inside a READ ONLY transaction."""
    load_dotenv()
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL environment variable is not set.")

    conn = psycopg2.connect(db_url)
    try:
        conn.set_session(readonly=True, autocommit=False)
        with conn.cursor() as cur:
            cur.execute("SET TRANSACTION READ ONLY;")

            cur.execute("SELECT id, email, is_active FROM public.users ORDER BY id;")
            users_rows = cur.fetchall()
            users_map: Dict[int, Dict[str, Any]] = {}
            for u_id, u_email, u_active in users_rows:
                email_str = str(u_email or "").strip().lower()
                users_map[u_id] = {
                    "user_id": u_id,
                    "is_synthetic_candidate": email_str.endswith("@candidate.digigarment.local"),
                    "is_active": bool(u_active),
                }

            cur.execute(
                "SELECT id, account_type, is_active, email_verified FROM public.public_users ORDER BY id;"
            )
            pub_rows = cur.fetchall()
            pub_map: Dict[int, Dict[str, Any]] = {}
            for p_id, acct_type, p_active, email_ver in pub_rows:
                pub_map[p_id] = {
                    "public_user_id": p_id,
                    "account_type": str(acct_type or ""),
                    "is_active": bool(p_active),
                    "email_verified": bool(email_ver),
                }

            # Check company_profiles to detect any dual-role or employer mobile conflicts
            company_user_ids: Set[int] = set()
            company_mobiles: Set[str] = set()
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM information_schema.tables
                    WHERE table_schema = 'public'
                      AND table_name = 'company_profiles'
                );
                """
            )
            if bool(cur.fetchone()[0]):
                cur.execute("SELECT user_id, mobile, whatsapp FROM public.company_profiles;")
                for c_uid, c_mob, c_wa in cur.fetchall():
                    if c_uid is not None:
                        company_user_ids.add(int(c_uid))
                    for raw_m in (c_mob, c_wa):
                        nm = normalize_indian_mobile(raw_m)
                        if is_valid_indian_mobile(nm):
                            company_mobiles.add(nm)

            cur.execute(
                "SELECT id, user_id, full_name, mobile FROM public.individual_profiles ORDER BY id;"
            )
            ind_rows = cur.fetchall()

            cur.execute(
                "SELECT id, user_id, full_name, mobile, whatsapp_number FROM public.job_seeker_profiles ORDER BY id;"
            )
            jsp_rows = cur.fetchall()

            # Track 1:1 user_id integrity in individual_profiles and job_seeker_profiles
            ind_user_id_counts: Counter = Counter(
                int(r[1]) for r in ind_rows if r[1] is not None
            )
            jsp_user_id_counts: Counter = Counter(
                int(r[1]) for r in jsp_rows if r[1] is not None
            )

            ind_by_mobile: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
            ind_mobile_counts: Counter = Counter()
            for ind_id, ind_user_id, full_name, mobile in ind_rows:
                norm_m = normalize_indian_mobile(mobile)
                pub_record = pub_map.get(ind_user_id)
                # Verify individual_profiles.user_id -> public_users.id reference & 1:1 integrity
                fk_valid = (
                    ind_user_id is not None
                    and pub_record is not None
                    and pub_record["public_user_id"] == ind_user_id
                    and ind_user_id_counts[int(ind_user_id)] == 1
                )
                if is_valid_indian_mobile(norm_m):
                    ind_mobile_counts[norm_m] += 1
                    ind_by_mobile[norm_m].append(
                        {
                            "individual_profile_id": ind_id,
                            "individual_profile_user_id": ind_user_id,
                            "public_user_id": pub_record["public_user_id"] if pub_record else None,
                            "fk_reference_valid": fk_valid,
                            "norm_name": normalize_name(full_name),
                            "account_type": pub_record["account_type"] if pub_record else None,
                            "public_user_is_active": pub_record["is_active"] if pub_record else False,
                            "in_company_profiles": (ind_user_id in company_user_ids),
                        }
                    )

            jsp_mobile_counts: Counter = Counter()
            for _, _, _, mobile, _ in jsp_rows:
                norm_m = normalize_indian_mobile(mobile)
                if is_valid_indian_mobile(norm_m):
                    jsp_mobile_counts[norm_m] += 1

            category_counts: Counter = Counter()
            masked_proposals: List[Dict[str, Any]] = []

            for jsp_id, legacy_uid, full_name, mobile, _ in jsp_rows:
                norm_m = normalize_indian_mobile(mobile)
                norm_n = normalize_name(full_name)
                u_info = users_map.get(legacy_uid)
                legacy_user_valid = (
                    legacy_uid is not None
                    and u_info is not None
                    and u_info["user_id"] == legacy_uid
                    and u_info["is_synthetic_candidate"] is True
                    and u_info["is_active"] is True
                    and jsp_user_id_counts[int(legacy_uid)] == 1
                )

                if not is_valid_indian_mobile(norm_m):
                    category = "6_invalid_or_missing_mobile"
                    migration_status = "invalid_mobile_preserved"
                    conflict_reason = "INVALID_OR_MISSING_MOBILE"
                    mapped_pub_uid = None
                    mapped_ind_id = None
                elif jsp_mobile_counts[norm_m] > 1:
                    category = "5_duplicate_profile"
                    migration_status = "conflict_pending_manual_review"
                    conflict_reason = "DUPLICATE_MOBILE_IN_JOB_SEEKER_PROFILES"
                    mapped_pub_uid = None
                    mapped_ind_id = None
                else:
                    matches = ind_by_mobile.get(norm_m, [])
                    if len(matches) == 0 and norm_m not in company_mobiles:
                        if not legacy_user_valid:
                            category = "3_conflicting_match"
                            migration_status = "conflict_pending_manual_review"
                            conflict_reason = "LEGACY_USER_FK_OR_ROLE_CONFLICT"
                            mapped_pub_uid = None
                            mapped_ind_id = None
                        else:
                            category = "4_no_match"
                            migration_status = "unmatched_preserved"
                            conflict_reason = None
                            mapped_pub_uid = None
                            mapped_ind_id = None
                    elif (
                        len(matches) != 1
                        or norm_m in company_mobiles
                        or not legacy_user_valid
                        or not matches[0]["fk_reference_valid"]
                        or matches[0]["individual_profile_user_id"] != matches[0]["public_user_id"]
                        or matches[0]["account_type"] != "individual"
                        or not matches[0]["public_user_is_active"]
                        or matches[0]["in_company_profiles"]
                        or not norm_n
                        or not matches[0]["norm_name"]
                    ):
                        category = "3_conflicting_match"
                        migration_status = "conflict_pending_manual_review"
                        conflict_reason = "MULTI_ACCOUNT_FK_OR_ROLE_CONFLICT"
                        mapped_pub_uid = None
                        mapped_ind_id = None
                    elif matches[0]["norm_name"] == norm_n:
                        # Explicit assertion that individual_profiles.user_id == proposed public_users.id
                        assert (
                            matches[0]["individual_profile_user_id"] == matches[0]["public_user_id"]
                            and matches[0]["fk_reference_valid"] is True
                        ), "Relational integrity check failed between individual_profiles.user_id and public_users.id"
                        category = "1_exact_match"
                        migration_status = "linked_readonly"
                        conflict_reason = None
                        mapped_pub_uid = matches[0]["public_user_id"]
                        mapped_ind_id = matches[0]["individual_profile_id"]
                    else:
                        # Decision D3: Probable match MUST stay in conflict_pending_manual_review
                        # and MUST NOT populate mapped_public_user_id or mapped_individual_profile_id.
                        category = "2_probable_match"
                        migration_status = "conflict_pending_manual_review"
                        conflict_reason = "NAME_MISMATCH_PROBABLE"
                        mapped_pub_uid = None
                        mapped_ind_id = None

                category_counts[category] += 1
                if include_masked_proposals:
                    masked_proposals.append(
                        {
                            "legacy_job_seeker_profile_id": jsp_id,
                            "legacy_user_id": legacy_uid,
                            "masked_mobile": mask_mobile(mobile),
                            "category": category,
                            "proposed_migration_status": migration_status,
                            "proposed_mapped_public_user_id": mapped_pub_uid,
                            "proposed_mapped_individual_profile_id": mapped_ind_id,
                            "conflict_reason": conflict_reason,
                        }
                    )

            result: Dict[str, Any] = {
                "mode": "READ_ONLY_AUDIT",
                "table_totals": {
                    "users_total": len(users_rows),
                    "users_synthetic_candidate": sum(
                        1 for v in users_map.values() if v["is_synthetic_candidate"]
                    ),
                    "users_non_synthetic_admin": sum(
                        1 for v in users_map.values() if not v["is_synthetic_candidate"]
                    ),
                    "job_seeker_profiles_total": len(jsp_rows),
                    "public_users_total": len(pub_rows),
                    "public_users_individual": sum(
                        1 for v in pub_map.values() if v["account_type"] == "individual"
                    ),
                    "public_users_company": sum(
                        1 for v in pub_map.values() if v["account_type"] == "company"
                    ),
                    "individual_profiles_total": len(ind_rows),
                    "individual_profiles_duplicate_mobiles": sum(
                        1 for _, c in ind_mobile_counts.items() if c > 1
                    ),
                },
                "six_category_summary": {
                    "1_exact_match": category_counts["1_exact_match"],
                    "2_probable_match": category_counts["2_probable_match"],
                    "3_conflicting_match": category_counts["3_conflicting_match"],
                    "4_no_match": category_counts["4_no_match"],
                    "5_duplicate_profile": category_counts["5_duplicate_profile"],
                    "6_invalid_or_missing_mobile": category_counts["6_invalid_or_missing_mobile"],
                },
            }
            if include_masked_proposals:
                result["masked_mapping_proposals"] = masked_proposals

            return result
    finally:
        try:
            conn.rollback()
        finally:
            conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only legacy profile audit (zero database writes, masked output only)."
    )
    parser.add_argument(
        "--include-masked-proposals",
        action="store_true",
        help="Include per-ID masked mapping proposals (IDs + masked mobile only, no raw PII).",
    )
    args = parser.parse_args()

    summary = run_readonly_audit(include_masked_proposals=args.include_masked_proposals)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
