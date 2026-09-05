"""
Multi-Layer Duplicate Detection Service for Tiruppur Garment Job Ingestions.
Implements 4-Tier Detection Strategy:
  Tier 1: Exact Content / Media Hash Match (1.00)
  Tier 2: Recruiter Contact Anchor Match (Phone/WA + Similar Role/Dept)
  Tier 3: Company Entity + Job Role + Location Cluster Match
  Tier 4: Text Description / Requirements Similarity

Calculates composite duplicate confidence score (0.000 to 1.000)
and classifies into decision bands (High Duplicate, Possible Duplicate, Distinct Job).
"""

import re
import difflib
from typing import Dict, Any, Optional, List, Tuple

# Configurable decision thresholds
THRESHOLD_HIGH_DUPLICATE = 0.90
THRESHOLD_POSSIBLE_DUPLICATE = 0.70

class JobDeduplicator:
    def __init__(self, active_jobs: List[Dict[str, Any]], recent_sources: List[Dict[str, Any]] = None):
        self.active_jobs = active_jobs or []
        self.recent_sources = recent_sources or []

    def check_duplicate(
        self,
        extracted_data: Dict[str, Any],
        content_hash: Optional[str] = None,
        media_hash: Optional[str] = None
    ) -> Tuple[Optional[Dict[str, Any]], float, List[str], str]:
        """
        Evaluates extracted job data against active jobs and returns:
        (matched_job_dict_or_None, duplicate_score, reasons_list, decision_band)
        """
        reasons = []

        # --- CANDIDATE ATTRIBUTES ---
        incoming_role = (extracted_data.get("job_role") or "").strip().lower()
        incoming_dept = (extracted_data.get("department") or "").strip().lower()
        incoming_comp = (extracted_data.get("company_normalized_key") or extracted_data.get("company_name") or "").strip().lower()
        incoming_phone = (extracted_data.get("contact_phone") or "").replace(" ", "").replace("-", "")
        incoming_desc = (extracted_data.get("description") or "").strip().lower()

        # --- TIER 1: EXACT HASH MATCH (With Role Guardrail) ---
        if content_hash or media_hash:
            for job in self.active_jobs:
                job_r = (job.get("job_role") or "").strip().lower()
                role_match = (
                    not incoming_role or not job_r or 
                    incoming_role == job_r or 
                    incoming_role in job_r or job_r in incoming_role or
                    difflib.SequenceMatcher(None, incoming_role, job_r).ratio() >= 0.75
                )
                if role_match and ((content_hash and job.get("content_hash") == content_hash) or \
                   (media_hash and (job.get("source_hash") == media_hash or job.get("media_hash") == media_hash))):
                    reasons.append(f"Tier 1: Exact cryptographic SHA-256 hash & role match with Job #{job['id']}")
                    return (job, 1.0, reasons, "HIGH_DUPLICATE")

            if self.recent_sources:
                for src in self.recent_sources:
                    if (content_hash and src.get("content_hash") == content_hash) or \
                       (media_hash and (src.get("media_hash") == media_hash or src.get("source_hash") == media_hash)):
                        matched_id = src.get("job_id") or src.get("matched_job_id")
                        matched_job = next((j for j in self.active_jobs if j.get("id") == matched_id), None)
                        if matched_job:
                            job_r = (matched_job.get("job_role") or "").strip().lower()
                            role_match = (
                                not incoming_role or not job_r or 
                                incoming_role == job_r or 
                                incoming_role in job_r or job_r in incoming_role or
                                difflib.SequenceMatcher(None, incoming_role, job_r).ratio() >= 0.75
                            )
                            if role_match:
                                reasons.append(f"Tier 1: Matched source hash & role of existing Job #{matched_id}")
                                return (matched_job, 1.0, reasons, "HIGH_DUPLICATE")

        # --- CANDIDATE COMPARISONS ACROSS ACTIVE JOBS ---
        best_match = None
        highest_score = 0.0
        best_reasons = []

        for job in self.active_jobs:
            score = 0.0
            job_reasons = []

            job_role = (job.get("job_role") or "").strip().lower()
            job_dept = (job.get("department") or "").strip().lower()
            job_comp = (job.get("company_name") or "").strip().lower()
            job_phone = (job.get("contact_phone") or job.get("contact_whatsapp") or "").replace(" ", "").replace("-", "")
            job_desc = (job.get("description") or "").strip().lower()

            # Guardrail: If departments or roles are fundamentally different, penalize heavily
            if incoming_dept and job_dept and incoming_dept != job_dept and incoming_dept != "other" and job_dept != "other":
                # Different department (e.g. Merchandising vs Sewing) - NOT a duplicate
                continue

            # Role Match Score (Weight: 0.35)
            role_sim = difflib.SequenceMatcher(None, incoming_role, job_role).ratio() if incoming_role and job_role else 0.0
            if incoming_role == job_role or role_sim >= 0.85:
                score += 0.35
                job_reasons.append(f"Role match: '{extracted_data.get('job_role')}'")
            elif role_sim >= 0.65:
                score += 0.20 * role_sim
                job_reasons.append(f"Partial role similarity: {int(role_sim*100)}%")
            else:
                # Disparate roles within same department (e.g. Merchandiser vs Quality Auditor)
                continue

            # Contact Phone Match (Weight: 0.35)
            if incoming_phone and job_phone and len(incoming_phone) >= 10 and len(job_phone) >= 10:
                if incoming_phone[-10:] == job_phone[-10:]:
                    score += 0.35
                    job_reasons.append(f"Tier 2: Recruiter phone match ({extracted_data.get('contact_phone')})")

            # Company Entity Match (Weight: 0.20)
            comp_sim = difflib.SequenceMatcher(None, incoming_comp, job_comp).ratio() if incoming_comp and job_comp else 0.0
            if incoming_comp and job_comp and (incoming_comp in job_comp or job_comp in incoming_comp or comp_sim >= 0.80):
                score += 0.20
                job_reasons.append(f"Tier 3: Company entity match ('{job.get('company_name')}')")

            # Description / Text Similarity (Weight: 0.10)
            if incoming_desc and job_desc:
                desc_sim = difflib.SequenceMatcher(None, incoming_desc[:200], job_desc[:200]).ratio()
                if desc_sim >= 0.60:
                    score += 0.10 * desc_sim
                    job_reasons.append(f"Tier 4: Text content similarity: {int(desc_sim*100)}%")

            final_score = round(min(score, 1.0), 3)
            if final_score > highest_score:
                highest_score = final_score
                best_match = job
                best_reasons = job_reasons

        # Determine Decision Band
        if highest_score >= THRESHOLD_HIGH_DUPLICATE:
            band = "HIGH_DUPLICATE"
        elif highest_score >= THRESHOLD_POSSIBLE_DUPLICATE:
            band = "POSSIBLE_DUPLICATE"
        else:
            band = "DISTINCT_JOB"

        return (best_match, highest_score, best_reasons, band)
