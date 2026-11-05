"""
DigiGarment Application & Analytics Event Reconciliation Script
================================================================
Prepared in Gate B / Corrected in Gate B.1 & Gate B.2
(Preparation Only – DO NOT EXECUTE without authorization).

Safety Guarantees:
  1. Default mode is strictly DRY RUN (`SET TRANSACTION READ ONLY`, `readonly=True`).
  2. Write mode (`--apply`) is hard-disabled (`ALLOW_RECONCILIATION_WRITES = False`) and
     additionally requires `DG_GATE_C_RECONCILE_APPROVED=TRUE` so no INSERT, UPDATE,
     DELETE, or DDL can occur until separately unlocked in a future gate.
  3. Prevents BIGINT/INT4 overflow:
       - Validates numeric `application_id` strings using bounded regex `^[1-9][0-9]{0,17}$`
         (1 to 18 digits, positive non-zero, guaranteed `< 10^18 < BIGINT_MAX`) and checks
         32-bit `INT4` bounds (`<= 2147483647`). Strings exceeding 18 digits or failing
         format checks are quarantined without casting.
  4. Verifies primary `application_id`, `job_id`, and expected `user_id` before classifying
     an event as an `exact_match`.
  5. Inspects event `metadata` JSONB for contradictory identity or context fields even when
     primary `application_id`, `job_id`, and `user_id` columns otherwise match, routing any
     contradictory event to `contradictory_metadata_identity_events`
     (`QUARANTINED_CONTRADICTORY_METADATA_IDENTITY`) and skipping automatic backfill.
  6. Detects multiple historical events referring to the same `application_id` and classifies
     them under `duplicate_application_events` (`QUARANTINED_DUPLICATE_EVENTS_FOR_SAME_APPLICATION`).
  7. Preserves Decision D4 for legacy application ID 16:
       - `job_analytics_events.user_id` is ALWAYS `NULL` (`a.candidate_user_id`).
       - `legacy_user_id = 9` and `legacy_job_seeker_profile_id = 8` are placed strictly inside
         `metadata` JSONB. Never uses `users.id` as `job_analytics_events.user_id`.
"""

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

import psycopg2
from dotenv import load_dotenv

# Hard gate lock: keep False until explicitly authorized in a future reconciliation gate
ALLOW_RECONCILIATION_WRITES: bool = False

SAFE_POSITIVE_BIGINT_RE = re.compile(r"^[1-9][0-9]{0,17}$")
MAX_INT4 = 2_147_483_647
DETERMINISTIC_PREFIX = "app_submit:app_id:"
ALLOWED_REPORT_EVENT_TYPES = frozenset({"application_submit", "application_submitted"})


def parse_safe_app_id(raw_val: Optional[str]) -> Tuple[Optional[int], Optional[str]]:
    """
    Parse a string into a positive 32-bit integer ID without BIGINT/INT4 overflow.
    Returns (parsed_int, error_reason).
    """
    if raw_val is None or isinstance(raw_val, bool):
        return None, "MISSING_APPLICATION_ID"
    s = str(raw_val).strip()
    if not s:
        return None, "EMPTY_APPLICATION_ID"
    if not SAFE_POSITIVE_BIGINT_RE.match(s):
        if re.match(r"^[0-9]{19,}$", s):
            return None, "NUMERIC_OVERFLOW_EXCEEDS_18_DIGITS"
        return None, "NON_NUMERIC_OR_INVALID_FORMAT"
    val = int(s)
    if val > MAX_INT4:
        return None, "NUMERIC_OVERFLOW_EXCEEDS_INT4_MAX"
    return val, None


def _sanitize_raw_id_for_report(raw_val: Optional[Any]) -> Optional[str]:
    """
    Ensure raw metadata ID strings emitted in diagnostic reports only expose
    positive numeric IDs within PostgreSQL INT4 range (1 .. 2,147,483,647).
    Masks values outside INT4 range, phone-like numeric values, arbitrary text,
    names, email addresses, and malformed metadata.
    """
    if raw_val is None:
        return None
    if isinstance(raw_val, bool):
        return "<MASKED_NON_NUMERIC_OR_OVERFLOW_ID>"
    s = str(raw_val).strip()
    if not s:
        return "<MASKED_NON_NUMERIC_OR_OVERFLOW_ID>"
    parsed_id, err = parse_safe_app_id(s)
    if err is not None or parsed_id is None or s != str(parsed_id):
        return "<MASKED_NON_NUMERIC_OR_OVERFLOW_ID>"
    return str(parsed_id)


def _sanitize_event_type_for_report(raw_val: Optional[Any]) -> str:
    """
    Ensure event_type strings emitted in diagnostic reports only display exact
    allowed values ('application_submit' or 'application_submitted').
    All other values are masked so names, free-text, or PII never leak.
    """
    if isinstance(raw_val, str):
        s = raw_val.strip()
        if s in ALLOWED_REPORT_EVENT_TYPES:
            return s
    return "<MASKED_UNEXPECTED_EVENT_TYPE>"


def _sanitize_event_id_for_report(raw_val: Optional[Any]) -> Optional[str]:
    """
    Ensure event_id values emitted in diagnostic reports only allow None (NULL)
    or the exact deterministic format:
      app_submit:app_id:<positive INT4 application ID>
    Masks every other event_id so arbitrary alphanumeric strings, names,
    phone numbers, or malformed IDs are never exposed.
    """
    if raw_val is None:
        return None
    if not isinstance(raw_val, str):
        return "<MASKED_UNEXPECTED_EVENT_ID>"
    s = raw_val.strip()
    if not s.startswith(DETERMINISTIC_PREFIX):
        return "<MASKED_UNEXPECTED_EVENT_ID>"
    suffix = s[len(DETERMINISTIC_PREFIX) :]
    parsed_id, err = parse_safe_app_id(suffix)
    if err is not None or parsed_id is None or suffix != str(parsed_id):
        return "<MASKED_UNEXPECTED_EVENT_ID>"
    return f"{DETERMINISTIC_PREFIX}{parsed_id}"


def _norm_phone(raw_val: Optional[Any]) -> str:
    digits = re.sub(r"\D", "", str(raw_val or ""))
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    return digits


def _norm_text(raw_val: Optional[Any]) -> str:
    return re.sub(r"\s+", " ", str(raw_val or "").strip().lower())


def detect_metadata_identity_contradictions(
    meta_obj: Dict[str, Any],
    app: Dict[str, Any],
    evt_id_str: Optional[str],
) -> List[str]:
    """
    Inspect `metadata` JSONB for contradictory identity or context fields even when
    primary `application_id`, `job_id`, and `user_id` columns otherwise match.
    Returns non-PII contradiction reason codes only.
    """
    contradictions: List[str] = []
    if not isinstance(meta_obj, dict):
        return contradictions

    app_id = app["application_id"]
    expected_job_id = app["job_id"]
    expected_cand_uid = app["candidate_user_id"]
    expected_ind_pid = app.get("individual_profile_id")
    expected_leg_uid = app["legacy_user_id"]
    expected_leg_jsp_id = app["legacy_job_seeker_profile_id"]

    # 1. metadata.job_id vs application.job_id
    if "job_id" in meta_obj and meta_obj["job_id"] is not None:
        parsed_jid, j_err = parse_safe_app_id(str(meta_obj["job_id"]))
        if j_err is not None or parsed_jid != expected_job_id:
            contradictions.append("METADATA_JOB_ID_CONTRADICTS_APPLICATION_JOB_ID")

    # 2. metadata.user_id / metadata.candidate_user_id vs application identity
    for key_name in ("user_id", "candidate_user_id"):
        if key_name in meta_obj and meta_obj[key_name] is not None:
            if expected_cand_uid is None:
                contradictions.append(
                    f"METADATA_{key_name.upper()}_PRESENT_ON_LEGACY_APPLICATION"
                )
            else:
                parsed_uid, u_err = parse_safe_app_id(str(meta_obj[key_name]))
                if u_err is not None or parsed_uid != expected_cand_uid:
                    contradictions.append(
                        f"METADATA_{key_name.upper()}_CONTRADICTS_CANDIDATE_USER_ID"
                    )

    # 3. metadata.legacy_user_id vs application.legacy_user_id
    if "legacy_user_id" in meta_obj and meta_obj["legacy_user_id"] is not None:
        if expected_leg_uid is None:
            contradictions.append(
                "METADATA_LEGACY_USER_ID_PRESENT_ON_NON_LEGACY_APPLICATION"
            )
        else:
            parsed_luid, lu_err = parse_safe_app_id(str(meta_obj["legacy_user_id"]))
            if lu_err is not None or parsed_luid != expected_leg_uid:
                contradictions.append(
                    "METADATA_LEGACY_USER_ID_CONTRADICTS_APPLICATION"
                )

    # 4. metadata.individual_profile_id / metadata.profile_id vs application.individual_profile_id
    for key_name in ("individual_profile_id", "profile_id"):
        if key_name in meta_obj and meta_obj[key_name] is not None:
            if expected_ind_pid is None:
                contradictions.append(
                    f"METADATA_{key_name.upper()}_PRESENT_WHEN_APPLICATION_HAS_NONE"
                )
            else:
                parsed_pid, p_err = parse_safe_app_id(str(meta_obj[key_name]))
                if p_err is not None or parsed_pid != expected_ind_pid:
                    contradictions.append(
                        f"METADATA_{key_name.upper()}_CONTRADICTS_APPLICATION"
                    )

    # 5. metadata.job_seeker_profile_id / metadata.legacy_job_seeker_profile_id
    for key_name in ("job_seeker_profile_id", "legacy_job_seeker_profile_id"):
        if key_name in meta_obj and meta_obj[key_name] is not None:
            if expected_leg_jsp_id is None:
                contradictions.append(
                    f"METADATA_{key_name.upper()}_PRESENT_WHEN_APPLICATION_HAS_NONE"
                )
            else:
                parsed_jsp, jsp_err = parse_safe_app_id(str(meta_obj[key_name]))
                if jsp_err is not None or parsed_jsp != expected_leg_jsp_id:
                    contradictions.append(
                        f"METADATA_{key_name.upper()}_CONTRADICTS_APPLICATION"
                    )

    # 6. metadata.event_id vs deterministic event_id / column event_id
    if "event_id" in meta_obj and meta_obj["event_id"] is not None:
        meta_ev_id = str(meta_obj["event_id"]).strip()
        expected_det = f"{DETERMINISTIC_PREFIX}{app_id}"
        if meta_ev_id != expected_det and (
            evt_id_str is None or meta_ev_id != str(evt_id_str).strip()
        ):
            contradictions.append("METADATA_EVENT_ID_CONTRADICTS_EXPECTED_EVENT_ID")

    # 7. Contradictory PII fields inside metadata (compared in memory only; never emitted)
    for email_key in ("applicant_email", "email"):
        if email_key in meta_obj and meta_obj[email_key] is not None:
            meta_email = _norm_text(meta_obj[email_key])
            app_email = app.get("_norm_email", "")
            if meta_email and (not app_email or meta_email != app_email):
                contradictions.append("METADATA_APPLICANT_EMAIL_CONTRADICTS_APPLICATION")
                break

    for phone_key in ("applicant_phone", "phone", "mobile"):
        if phone_key in meta_obj and meta_obj[phone_key] is not None:
            meta_phone = _norm_phone(meta_obj[phone_key])
            app_phone = app.get("_norm_phone", "")
            if str(meta_obj[phone_key]).strip() and (
                not meta_phone or not app_phone or meta_phone != app_phone
            ):
                contradictions.append("METADATA_APPLICANT_PHONE_CONTRADICTS_APPLICATION")
                break

    for name_key in ("applicant_name", "full_name"):
        if name_key in meta_obj and meta_obj[name_key] is not None:
            meta_name = _norm_text(meta_obj[name_key])
            app_name = app.get("_norm_name", "")
            if meta_name and (not app_name or meta_name != app_name):
                contradictions.append("METADATA_APPLICANT_NAME_CONTRADICTS_APPLICATION")
                break

    return contradictions


def inspect_reconciliation_state(cur, has_event_id_col: bool) -> Dict[str, Any]:
    """
    Inspect `job_applications` and `job_analytics_events` in READ ONLY mode and classify:
      - exact_matches (1:1 verified application_id + job_id + user identity + clean metadata)
      - proposed_backfill_events (0 candidate events referencing application_id)
      - contradictory_metadata_identity_events (primary fields match, but metadata has contradictory identity)
      - duplicate_application_events (>1 events referencing the same application_id)
      - inconsistent_identity_or_job_events (application_id matches, but job_id/user_id mismatches)
      - orphaned_analytics_events (valid application_id that does not exist in job_applications)
      - ambiguous_quarantined_events (missing, non-numeric, or overflow application_id)
    """
    cur.execute(
        """
        SELECT
            a.id,
            a.job_id,
            a.candidate_user_id,
            a.individual_profile_id,
            a.user_id AS legacy_user_id,
            a.job_seeker_profile_id AS legacy_job_seeker_profile_id,
            a.status,
            a.applied_at,
            a.applicant_email,
            a.applicant_phone,
            a.applicant_name
        FROM public.job_applications a
        ORDER BY a.id;
        """
    )
    apps_by_id: Dict[int, Dict[str, Any]] = {}
    for r in cur.fetchall():
        apps_by_id[int(r[0])] = {
            "application_id": int(r[0]),
            "job_id": int(r[1]) if r[1] is not None else None,
            "candidate_user_id": int(r[2]) if r[2] is not None else None,
            "individual_profile_id": int(r[3]) if r[3] is not None else None,
            "legacy_user_id": int(r[4]) if r[4] is not None else None,
            "legacy_job_seeker_profile_id": int(r[5]) if r[5] is not None else None,
            "status": str(r[6] or ""),
            "applied_at": r[7].isoformat() if r[7] else None,
            # Normalized in-memory comparison attributes (never included in output)
            "_norm_email": _norm_text(r[8]),
            "_norm_phone": _norm_phone(r[9]),
            "_norm_name": _norm_text(r[10]),
        }

    if has_event_id_col:
        cur.execute(
            """
            SELECT
                e.id,
                e.event_id,
                e.event_type,
                e.job_id,
                e.user_id,
                jsonb_typeof(e.metadata) AS meta_type,
                CASE
                    WHEN jsonb_typeof(e.metadata) = 'object' THEN e.metadata->>'application_id'
                    ELSE NULL
                END AS raw_meta_app_id,
                CASE
                    WHEN jsonb_typeof(e.metadata) = 'object' THEN e.metadata->>'legacy_user_id'
                    ELSE NULL
                END AS raw_meta_legacy_uid,
                e.metadata,
                e.created_at
            FROM public.job_analytics_events e
            WHERE e.event_type IN ('application_submit', 'application_submitted')
               OR (e.event_id IS NOT NULL AND e.event_id LIKE 'app_submit:app_id:%')
            ORDER BY e.id;
            """
        )
    else:
        cur.execute(
            """
            SELECT
                e.id,
                NULL::varchar AS event_id,
                e.event_type,
                e.job_id,
                e.user_id,
                jsonb_typeof(e.metadata) AS meta_type,
                CASE
                    WHEN jsonb_typeof(e.metadata) = 'object' THEN e.metadata->>'application_id'
                    ELSE NULL
                END AS raw_meta_app_id,
                CASE
                    WHEN jsonb_typeof(e.metadata) = 'object' THEN e.metadata->>'legacy_user_id'
                    ELSE NULL
                END AS raw_meta_legacy_uid,
                e.metadata,
                e.created_at
            FROM public.job_analytics_events e
            WHERE e.event_type IN ('application_submit', 'application_submitted')
            ORDER BY e.id;
            """
        )

    raw_events = cur.fetchall()

    ambiguous_quarantined_events: List[Dict[str, Any]] = []
    orphaned_analytics_events: List[Dict[str, Any]] = []
    events_by_app_id: Dict[int, List[Dict[str, Any]]] = defaultdict(list)

    for row in raw_events:
        (
            evt_row_id,
            evt_id_str,
            evt_type,
            evt_job_id,
            evt_user_id,
            meta_type,
            raw_meta_app_id,
            raw_meta_legacy_uid,
            meta_obj,
            created_at,
        ) = row

        evt_info: Dict[str, Any] = {
            "event_row_id": int(evt_row_id),
            "event_id": _sanitize_event_id_for_report(evt_id_str),
            "event_type": _sanitize_event_type_for_report(evt_type),
            "job_id": int(evt_job_id) if evt_job_id is not None else None,
            "user_id": int(evt_user_id) if evt_user_id is not None else None,
            "raw_metadata_application_id": _sanitize_raw_id_for_report(raw_meta_app_id),
            "raw_metadata_legacy_user_id": _sanitize_raw_id_for_report(raw_meta_legacy_uid),
            "created_at": created_at.isoformat() if created_at else None,
        }

        det_app_id: Optional[int] = None
        det_err: Optional[str] = None
        if evt_id_str and str(evt_id_str).startswith(DETERMINISTIC_PREFIX):
            suffix = str(evt_id_str)[len(DETERMINISTIC_PREFIX) :]
            det_app_id, det_err = parse_safe_app_id(suffix)
            if det_err is not None:
                ambiguous_quarantined_events.append(
                    {
                        **evt_info,
                        "status": f"QUARANTINED_INVALID_EVENT_ID_SUFFIX:{det_err}",
                    }
                )
                continue

        meta_app_id: Optional[int] = None
        meta_err: Optional[str] = None
        if meta_type == "object" and raw_meta_app_id is not None:
            meta_app_id, meta_err = parse_safe_app_id(raw_meta_app_id)
        elif det_app_id is None:
            meta_err = (
                "METADATA_NOT_JSON_OBJECT"
                if meta_type != "object"
                else "MISSING_APPLICATION_ID"
            )

        if meta_err is not None and det_app_id is None:
            ambiguous_quarantined_events.append(
                {
                    **evt_info,
                    "status": f"QUARANTINED_INVALID_OR_OVERFLOW_APPLICATION_ID:{meta_err}",
                }
            )
            continue

        if det_app_id is not None and meta_app_id is not None and det_app_id != meta_app_id:
            ambiguous_quarantined_events.append(
                {
                    **evt_info,
                    "status": "QUARANTINED_CONFLICTING_EVENT_ID_VS_METADATA_APPLICATION_ID",
                }
            )
            continue

        if det_app_id is not None and meta_err is not None and raw_meta_app_id is not None:
            ambiguous_quarantined_events.append(
                {
                    **evt_info,
                    "status": f"QUARANTINED_MALFORMED_METADATA_APPLICATION_ID:{meta_err}",
                }
            )
            continue

        resolved_app_id = det_app_id if det_app_id is not None else meta_app_id
        assert resolved_app_id is not None

        if resolved_app_id not in apps_by_id:
            orphaned_analytics_events.append(
                {
                    **evt_info,
                    "referenced_application_id": resolved_app_id,
                    "status": "ORPHANED_APPLICATION_ID_NOT_IN_JOB_APPLICATIONS",
                }
            )
            continue

        evt_info["resolved_application_id"] = resolved_app_id
        evt_info["_meta_obj"] = meta_obj if isinstance(meta_obj, dict) else {}
        evt_info["_raw_meta_legacy_uid"] = raw_meta_legacy_uid
        evt_info["_raw_event_id"] = evt_id_str
        evt_info["_raw_event_type"] = str(evt_type or "").strip()
        events_by_app_id[resolved_app_id].append(evt_info)

    exact_matches: List[Dict[str, Any]] = []
    contradictory_metadata_identity_events: List[Dict[str, Any]] = []
    duplicate_application_events: List[Dict[str, Any]] = []
    inconsistent_identity_or_job_events: List[Dict[str, Any]] = []
    quarantined_applications_skipped: List[Dict[str, Any]] = []
    proposed_backfill_events: List[Dict[str, Any]] = []

    for app_id, app in apps_by_id.items():
        candidate_events = events_by_app_id.get(app_id, [])

        # Case A: Zero events reference this application -> eligible for backfill
        if len(candidate_events) == 0:
            # Decision D4: analytics user_id MUST be candidate_user_id (NULL for legacy ID 16)
            analytics_user_id = app["candidate_user_id"]
            metadata_payload: Dict[str, Any] = {
                "application_id": app_id,
                "reconciled": True,
                "reconciled_from": "job_applications",
            }
            if app["legacy_user_id"] is not None:
                metadata_payload["legacy_user_id"] = app["legacy_user_id"]
            if app["legacy_job_seeker_profile_id"] is not None:
                metadata_payload["legacy_job_seeker_profile_id"] = app[
                    "legacy_job_seeker_profile_id"
                ]

            proposed_backfill_events.append(
                {
                    "application_id": app_id,
                    "deterministic_event_id": f"{DETERMINISTIC_PREFIX}{app_id}",
                    "event_type": "application_submit",
                    "job_id": app["job_id"],
                    "analytics_user_id": analytics_user_id,
                    "metadata": metadata_payload,
                    "applied_at": app["applied_at"],
                }
            )
            continue

        # Verify primary job_id and expected user_id for every candidate event referencing app_id
        mismatch_reasons_by_event: List[Tuple[Dict[str, Any], List[str]]] = []
        metadata_contradictions_by_event: List[Tuple[Dict[str, Any], List[str]]] = []

        for ev in candidate_events:
            reasons: List[str] = []
            if ev.get("_raw_event_type") not in ALLOWED_REPORT_EVENT_TYPES:
                reasons.append("UNEXPECTED_EVENT_TYPE")
            if ev["job_id"] is None or ev["job_id"] != app["job_id"]:
                reasons.append(
                    f"JOB_ID_MISMATCH:event={ev['job_id']},expected={app['job_id']}"
                )

            if app["candidate_user_id"] is not None:
                if ev["user_id"] != app["candidate_user_id"]:
                    reasons.append(
                        f"USER_ID_MISMATCH:event={ev['user_id']},expected_candidate_user_id={app['candidate_user_id']}"
                    )
            else:
                if ev["user_id"] is not None:
                    reasons.append(
                        f"LEGACY_APP_NON_NULL_USER_ID:event={ev['user_id']},expected=None"
                    )
                ev_raw_leg_uid = ev.get("_raw_meta_legacy_uid")
                if ev_raw_leg_uid is not None:
                    parsed_leg_uid, leg_err = parse_safe_app_id(ev_raw_leg_uid)
                    if leg_err is not None or parsed_leg_uid != app["legacy_user_id"]:
                        reasons.append(
                            f"METADATA_LEGACY_USER_ID_MISMATCH:event={_sanitize_raw_id_for_report(ev_raw_leg_uid)},expected={app['legacy_user_id']}"
                        )

            if reasons:
                mismatch_reasons_by_event.append((ev, reasons))
            else:
                # Primary fields match: now inspect metadata JSONB for contradictory identity fields
                meta_contradictions = detect_metadata_identity_contradictions(
                    ev.get("_meta_obj", {}), app, ev.get("_raw_event_id")
                )
                if meta_contradictions:
                    metadata_contradictions_by_event.append((ev, meta_contradictions))

        # Strip internal `_meta_obj`, `_raw_meta_legacy_uid`, `_raw_event_id`, and `_raw_event_type`
        # before serializing any event record
        for ev in candidate_events:
            ev.pop("_meta_obj", None)
            ev.pop("_raw_meta_legacy_uid", None)
            ev.pop("_raw_event_id", None)
            ev.pop("_raw_event_type", None)

        # Case B: Primary job_id or user_id mismatch
        if mismatch_reasons_by_event:
            for ev, reasons in mismatch_reasons_by_event:
                inconsistent_identity_or_job_events.append(
                    {
                        **ev,
                        "expected_job_id": app["job_id"],
                        "expected_candidate_user_id": app["candidate_user_id"],
                        "expected_legacy_user_id": app["legacy_user_id"],
                        "mismatch_reasons": reasons,
                        "status": "QUARANTINED_MISMATCHED_JOB_OR_USER_IDENTITY",
                    }
                )
            quarantined_applications_skipped.append(
                {
                    "application_id": app_id,
                    "reason": "QUARANTINED_MISMATCHED_JOB_OR_USER_IDENTITY",
                    "candidate_event_row_ids": [e["event_row_id"] for e in candidate_events],
                }
            )
            continue

        # Case C: Primary fields match, but metadata JSONB contains contradictory identity information
        if metadata_contradictions_by_event:
            for ev, meta_reasons in metadata_contradictions_by_event:
                contradictory_metadata_identity_events.append(
                    {
                        **ev,
                        "expected_job_id": app["job_id"],
                        "expected_candidate_user_id": app["candidate_user_id"],
                        "expected_individual_profile_id": app["individual_profile_id"],
                        "expected_legacy_user_id": app["legacy_user_id"],
                        "contradictory_metadata_reasons": meta_reasons,
                        "status": "QUARANTINED_CONTRADICTORY_METADATA_IDENTITY",
                    }
                )
            quarantined_applications_skipped.append(
                {
                    "application_id": app_id,
                    "reason": "QUARANTINED_CONTRADICTORY_METADATA_IDENTITY",
                    "candidate_event_row_ids": [e["event_row_id"] for e in candidate_events],
                }
            )
            continue

        # Case D: Multiple events reference the same application_id
        if len(candidate_events) > 1:
            for ev in candidate_events:
                duplicate_application_events.append(
                    {
                        **ev,
                        "duplicate_group_size": len(candidate_events),
                        "status": "QUARANTINED_DUPLICATE_EVENTS_FOR_SAME_APPLICATION",
                    }
                )
            quarantined_applications_skipped.append(
                {
                    "application_id": app_id,
                    "reason": "QUARANTINED_DUPLICATE_EVENTS_FOR_SAME_APPLICATION",
                    "candidate_event_row_ids": [e["event_row_id"] for e in candidate_events],
                }
            )
            continue

        # Case E: Exactly 1 event references app_id AND passes primary + metadata identity checks
        matched_ev = candidate_events[0]
        exact_matches.append(
            {
                "application_id": app_id,
                "job_id": app["job_id"],
                "candidate_user_id": app["candidate_user_id"],
                "legacy_user_id": app["legacy_user_id"],
                "matched_event_row_id": matched_ev["event_row_id"],
                "matched_event_id": matched_ev["event_id"],
                "matched_event_type": matched_ev["event_type"],
                "identity_verified": True,
                "metadata_identity_verified": True,
            }
        )

    return {
        "has_event_id_column": has_event_id_col,
        "exact_matches_count": len(exact_matches),
        "exact_matches": exact_matches,
        "missing_application_events_count": len(proposed_backfill_events),
        "proposed_backfill_events": proposed_backfill_events,
        "contradictory_metadata_identity_events_count": len(
            contradictory_metadata_identity_events
        ),
        "contradictory_metadata_identity_events": contradictory_metadata_identity_events,
        "duplicate_application_events_count": len(duplicate_application_events),
        "duplicate_application_events": duplicate_application_events,
        "inconsistent_identity_or_job_events_count": len(
            inconsistent_identity_or_job_events
        ),
        "inconsistent_identity_or_job_events": inconsistent_identity_or_job_events,
        "quarantined_applications_skipped_count": len(quarantined_applications_skipped),
        "quarantined_applications_skipped_from_backfill": quarantined_applications_skipped,
        "orphaned_analytics_events_count": len(orphaned_analytics_events),
        "orphaned_analytics_events": orphaned_analytics_events,
        "ambiguous_quarantined_events_count": len(ambiguous_quarantined_events),
        "ambiguous_quarantined_events": ambiguous_quarantined_events,
    }


def run_reconciliation(apply_writes: bool = False) -> Dict[str, Any]:
    """Execute dry-run reconciliation inspection (write mode disabled until future gate approval)."""
    load_dotenv()
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL environment variable is not set.")

    if apply_writes:
        if (
            not ALLOW_RECONCILIATION_WRITES
            or os.environ.get("DG_GATE_C_RECONCILE_APPROVED") != "TRUE"
        ):
            raise PermissionError(
                "Write mode is disabled (ALLOW_RECONCILIATION_WRITES=False). "
                "Separate future gate approval is required before --apply can be enabled."
            )

    conn = psycopg2.connect(db_url)
    try:
        if not apply_writes:
            conn.set_session(readonly=True, autocommit=False)

        with conn.cursor() as cur:
            if not apply_writes:
                cur.execute("SET TRANSACTION READ ONLY;")

            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'job_analytics_events'
                      AND column_name = 'event_id'
                );
                """
            )
            has_event_id_col = bool(cur.fetchone()[0])

            report = inspect_reconciliation_state(cur, has_event_id_col=has_event_id_col)
            report["mode"] = "APPLY_WRITES" if apply_writes else "DRY_RUN_READ_ONLY"
            report["inserted_count"] = 0

            if apply_writes:
                if not has_event_id_col:
                    raise RuntimeError(
                        "Cannot apply reconciliation before migration 014 adds job_analytics_events.event_id."
                    )

                inserted = 0
                for item in report["proposed_backfill_events"]:
                    # Decision D4 hard assertion: never allow legacy_user_id into analytics_user_id
                    legacy_uid = item["metadata"].get("legacy_user_id")
                    if legacy_uid is not None and item["analytics_user_id"] is not None:
                        if item["analytics_user_id"] == legacy_uid:
                            raise AssertionError(
                                "Decision D4 violation: legacy users.id must never be used as job_analytics_events.user_id."
                            )
                    if item["application_id"] == 16 and item["analytics_user_id"] is not None:
                        raise AssertionError(
                            "Decision D4 violation: legacy application ID 16 must use analytics_user_id = NULL."
                        )

                    cur.execute(
                        """
                        INSERT INTO public.job_analytics_events (
                            event_id,
                            event_type,
                            job_id,
                            user_id,
                            metadata,
                            created_at
                        )
                        VALUES (%s, %s, %s, %s, %s::jsonb, COALESCE(%s::timestamp, CURRENT_TIMESTAMP))
                        ON CONFLICT (event_id) WHERE event_id IS NOT NULL DO NOTHING;
                        """,
                        (
                            item["deterministic_event_id"],
                            item["event_type"],
                            item["job_id"],
                            item["analytics_user_id"],
                            json.dumps(item["metadata"]),
                            item["applied_at"],
                        ),
                    )
                    inserted += cur.rowcount

                conn.commit()
                report["inserted_count"] = inserted
            else:
                conn.rollback()

            return report
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()


def run_offline_sanitization_self_tests() -> Dict[str, Any]:
    """
    Execute offline unit and mock-cursor tests for PII sanitization and Decision D4
    without opening any database connection.
    """
    # 1. Valid small positive application ID
    assert _sanitize_raw_id_for_report("16") == "16"
    assert parse_safe_app_id("16") == (16, None)

    # 2. Maximum INT4 value (2,147,483,647)
    assert _sanitize_raw_id_for_report("2147483647") == "2147483647"
    assert parse_safe_app_id("2147483647") == (2147483647, None)

    # 3. Value exceeding INT4 maximum (2,147,483,648)
    assert (
        _sanitize_raw_id_for_report("2147483648")
        == "<MASKED_NON_NUMERIC_OR_OVERFLOW_ID>"
    )
    assert parse_safe_app_id("2147483648") == (
        None,
        "NUMERIC_OVERFLOW_EXCEEDS_INT4_MAX",
    )

    # 4. 10-digit phone-like number
    assert (
        _sanitize_raw_id_for_report("9876543210")
        == "<MASKED_NON_NUMERIC_OR_OVERFLOW_ID>"
    )

    # 5. Arbitrary alphabetic text
    assert (
        _sanitize_raw_id_for_report("Santhosh Kumar")
        == "<MASKED_NON_NUMERIC_OR_OVERFLOW_ID>"
    )

    # 6. Email-like text
    assert (
        _sanitize_raw_id_for_report("applicant@example.com")
        == "<MASKED_NON_NUMERIC_OR_OVERFLOW_ID>"
    )

    # 7. Allowed event type: application_submit
    assert _sanitize_event_type_for_report("application_submit") == "application_submit"

    # 8. Allowed event type: application_submitted
    assert (
        _sanitize_event_type_for_report("application_submitted")
        == "application_submitted"
    )

    # 9. Unexpected event type containing a person's name
    assert (
        _sanitize_event_type_for_report("application_submit_by_Ramesh_Kumar")
        == "<MASKED_UNEXPECTED_EVENT_TYPE>"
    )

    # 10. Valid deterministic event ID (and None)
    assert _sanitize_event_id_for_report("app_submit:app_id:16") == "app_submit:app_id:16"
    assert (
        _sanitize_event_id_for_report("app_submit:app_id:2147483647")
        == "app_submit:app_id:2147483647"
    )
    assert _sanitize_event_id_for_report(None) is None

    # 11. Arbitrary alphanumeric event ID
    assert (
        _sanitize_event_id_for_report("evt_99a8b7c6_custom_token")
        == "<MASKED_UNEXPECTED_EVENT_ID>"
    )

    # 12. Phone-like event ID (both bare and inside deterministic prefix)
    assert (
        _sanitize_event_id_for_report("9876543210")
        == "<MASKED_UNEXPECTED_EVENT_ID>"
    )
    assert (
        _sanitize_event_id_for_report("app_submit:app_id:9876543210")
        == "<MASKED_UNEXPECTED_EVENT_ID>"
    )

    # 13. Full report path audit via in-memory mock cursor (zero database connection)
    class _MockCursor:
        def __init__(self) -> None:
            self._step = 0

        def execute(self, _sql: str) -> None:
            self._step += 1

        def fetchall(self) -> List[Any]:
            if self._step == 1:
                # job_applications rows:
                #   row 1: legacy application id=16 (candidate_user_id=None, legacy_user_id=9, jsp_id=8)
                #   row 2: modern application id=25 (candidate_user_id=12, ind_profile_id=7)
                return [
                    (
                        16,
                        101,
                        None,
                        None,
                        9,
                        8,
                        "applied",
                        None,
                        "legacy@example.com",
                        "9876543210",
                        "Legacy Candidate",
                    ),
                    (
                        25,
                        202,
                        12,
                        7,
                        None,
                        None,
                        "applied",
                        None,
                        "modern@example.com",
                        "9123456789",
                        "Modern Candidate",
                    ),
                ]
            # job_analytics_events rows:
            #   event referencing app 25 with malformed event_id ("9876543210"),
            #   unexpected event_type with a person's name ("submitted_by_Ramesh_Kumar"),
            #   and malformed legacy_user_id ("ramesh@example.com")
            return [
                (
                    501,
                    "9876543210",
                    "submitted_by_Ramesh_Kumar",
                    202,
                    12,
                    "object",
                    "25",
                    "ramesh@example.com",
                    {"application_id": "25", "applicant_email": "ramesh@example.com"},
                    None,
                )
            ]

    mock_report = inspect_reconciliation_state(_MockCursor(), has_event_id_col=True)
    serialized = json.dumps(mock_report)

    # Ensure zero PII or raw unexpected strings appear anywhere in the serialized report
    for forbidden in (
        "Ramesh_Kumar",
        "9876543210",
        "ramesh@example.com",
        "legacy@example.com",
        "modern@example.com",
        "Legacy Candidate",
        "Modern Candidate",
    ):
        assert forbidden not in serialized, f"Leaked forbidden string: {forbidden}"

    # Verify fixed mismatch reason 'UNEXPECTED_EVENT_TYPE' (without concatenated raw value)
    mismatch_ev = mock_report["inconsistent_identity_or_job_events"][0]
    assert mismatch_ev["mismatch_reasons"] == ["UNEXPECTED_EVENT_TYPE"]
    assert mismatch_ev["event_type"] == "<MASKED_UNEXPECTED_EVENT_TYPE>"
    assert mismatch_ev["event_id"] == "<MASKED_UNEXPECTED_EVENT_ID>"
    assert (
        mismatch_ev["raw_metadata_legacy_user_id"]
        == "<MASKED_NON_NUMERIC_OR_OVERFLOW_ID>"
    )

    # Verify Decision D4 on proposed backfill for legacy application ID 16
    backfill_16 = mock_report["proposed_backfill_events"][0]
    assert backfill_16["application_id"] == 16
    assert backfill_16["analytics_user_id"] is None
    assert backfill_16["metadata"]["legacy_user_id"] == 9
    assert backfill_16["metadata"]["legacy_job_seeker_profile_id"] == 8

    return {"offline_sanitization_self_tests": "PASSED", "cases_verified": 13}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reconcile job_applications with job_analytics_events (Default: DRY RUN Read-Only)."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Disabled until separate future gate approval (ALLOW_RECONCILIATION_WRITES).",
    )
    parser.add_argument(
        "--self-test-offline",
        action="store_true",
        help="Run offline sanitization and D4 self-tests without connecting to any database.",
    )
    args = parser.parse_args()

    if args.self_test_offline:
        print(json.dumps(run_offline_sanitization_self_tests(), indent=2))
        return 0

    result = run_reconciliation(apply_writes=args.apply)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
