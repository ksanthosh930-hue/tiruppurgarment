import os
import re
import logging
from typing import Dict, Any, Optional, Tuple, List
from services.ai_provider import get_ai_provider, RuleBasedFallbackProvider, GeminiProvider
from services.normalizer import (
    normalize_company_name, normalize_department, normalize_job_role,
    normalize_location, normalize_phone_number
)

logger = logging.getLogger("DigiGarment.Extractor")

class StructuredJobExtractor:
    def __init__(self):
        self.provider = get_ai_provider()
        self.fallback_provider = RuleBasedFallbackProvider()

    def process_multi_job_ingestion(
        self,
        raw_text: Optional[str] = None,
        image_bytes: Optional[bytes] = None,
        image_mime: Optional[str] = None,
        force_ai: bool = False
    ) -> Dict[str, Any]:
        """
        Executes multi-job multi-modal extraction, taxonomy normalization,
        and vacancy segmentation with a Zero-AI Cost Deterministic First strategy.
        """
        ai_used = False
        ai_skipped = True
        ai_provider_name = "local_deterministic"
        
        use_ai = False
        ai_enabled_env = os.getenv("AI_ENABLED", "true").lower() in ["true", "1", "yes"]
        has_gemini_key = bool(os.getenv("GEMINI_API_KEY"))

        if (force_ai or image_bytes) and ai_enabled_env and has_gemini_key and isinstance(self.provider, GeminiProvider):
            use_ai = True

        if use_ai:
            try:
                extracted, raw_ai_resp, confidence, warnings = self.provider.extract_multi_jobs(
                    text=raw_text,
                    image_bytes=image_bytes,
                    image_mime=image_mime
                )
                ai_used = True
                ai_skipped = False
                ai_provider_name = "gemini"
            except Exception as e:
                logger.warning(f"AI multi-job extraction failed ({e}). Reverting to local deterministic parser.")
                extracted, raw_ai_resp, confidence, warnings = self.fallback_provider.extract_multi_jobs(
                    text=raw_text,
                    image_bytes=image_bytes,
                    image_mime=image_mime
                )
                warnings.append("AI rate limit/failure: parsed locally with zero cost.")
        else:
            extracted, raw_ai_resp, confidence, warnings = self.fallback_provider.extract_multi_jobs(
                text=raw_text,
                image_bytes=image_bytes,
                image_mime=image_mime
            )
            ai_used = False
            ai_skipped = True
            ai_provider_name = "local_deterministic"

        # Shared Post-Level Metadata Normalization
        raw_comp = extracted.get("company_name")
        clean_comp, norm_comp_key = normalize_company_name(raw_comp) if raw_comp else (None, "")
        location = normalize_location(extracted.get("location"))
        phone = normalize_phone_number(extracted.get("contact_phone"))
        wa = normalize_phone_number(extracted.get("contact_whatsapp")) or phone
        email = extracted.get("contact_email")
        website_source = extracted.get("website_source")
        
        walk_in_start_date = extracted.get("walk_in_start_date")
        walk_in_end_date = extracted.get("walk_in_end_date")
        walk_in_date_text = extracted.get("walk_in_date_text")
        interview_time = extracted.get("interview_time")
        immediate_joiners = extracted.get("immediate_joiners", False)

        # Priority resolution for phone from raw text if missing
        if not phone and raw_text:
            phones = re.findall(r'(?:\+91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}', raw_text)
            if not phones:
                phones = re.findall(r'\b[6-9]\d{9}\b', raw_text)
            if phones:
                phone = normalize_phone_number(phones[0])
                wa = phone

        raw_vacancies = extracted.get("vacancies", [])
        if not raw_vacancies:
            raw_vacancies = [{
                "vacancy_index": 1,
                "job_title": extracted.get("job_title") or "Garment Vacancy",
                "department": extracted.get("department") or "Production",
                "job_role": extracted.get("job_role") or "Garment Executive",
                "openings_count": 1,
                "confidence_score": confidence
            }]

        normalized_vacancies = []
        for idx, vac in enumerate(raw_vacancies, 1):
            vac_ctx = f"{vac.get('job_title', '')} {vac.get('job_role', '')} {vac.get('salary_text', '')} {vac.get('requirements', '')} {vac.get('remarks', '')}"
            vac_dept = normalize_department(vac.get("department"), text_context=vac_ctx)
            
            # Exact source designation preservation (NO semantic replacement on public role)
            raw_role_str = vac.get("source_role") or vac.get("job_role") or vac.get("job_title") or "Garment Role"
            _, vac_canonical_role = normalize_job_role(raw_role_str, dept=vac_dept)
            
            # Source designation is the public job role
            source_role_clean = str(raw_role_str).strip()
            
            vac_phone = normalize_phone_number(vac.get("contact_phone")) or phone
            vac_wa = normalize_phone_number(vac.get("contact_whatsapp")) or vac_phone or wa
            vac_email = vac.get("contact_email") or email
            vac_loc = normalize_location(vac.get("location")) if vac.get("location") else location
            
            openings = vac.get("openings_count", 1)
            try:
                openings = max(int(openings), 1)
            except (ValueError, TypeError):
                openings = 1
                
            role_ev = vac.get("role_evidence") or source_role_clean
            open_ev = vac.get("opening_evidence") or f"{openings} Openings"
            remarks_val = vac.get("remarks") or vac.get("requirements")
            
            vac_norm = {
                "vacancy_index": idx,
                "source_role": source_role_clean,
                "public_job_role": source_role_clean,
                "job_title": source_role_clean,
                "department": vac_dept,
                "job_role": source_role_clean,
                "canonical_role": vac_canonical_role,
                "company_name": clean_comp or None,
                "company_normalized_key": norm_comp_key if clean_comp else None,
                "openings_count": openings,
                "job_type": vac.get("job_type") or "Full Time",
                "location": vac_loc,
                "experience_min": vac.get("experience_min") or 0,
                "experience_max": vac.get("experience_max"),
                "salary_min": vac.get("salary_min"),
                "salary_max": vac.get("salary_max"),
                "salary_text": vac.get("salary_text"),
                "qualification": vac.get("qualification"),
                "gender": vac.get("gender") or "Male/Female",
                "skills": vac.get("skills") if isinstance(vac.get("skills"), list) else [source_role_clean],
                "remarks": remarks_val,
                "role_evidence": role_ev,
                "opening_evidence": open_ev,
                "remarks_evidence": remarks_val,
                "description": remarks_val or f"Requirement for {source_role_clean}.",
                "requirements": remarks_val,
                "walk_in_start_date": walk_in_start_date,
                "walk_in_end_date": walk_in_end_date,
                "walk_in_date_text": walk_in_date_text,
                "interview_time": interview_time,
                "immediate_joiners": immediate_joiners,
                "contact_phone": vac_phone,
                "contact_whatsapp": vac_wa,
                "contact_email": vac_email,
                "application_url": vac.get("application_url") or website_source,
                "confidence_score": round(float(vac.get("confidence_score", confidence)), 2),
                "decision": "PENDING",
                "missing_fields": vac.get("missing_fields", []),
                "warnings": vac.get("warnings", warnings)
            }
            normalized_vacancies.append(vac_norm)

        primary_vacancy = normalized_vacancies[0] if normalized_vacancies else {}
        total_openings = sum(v["openings_count"] for v in normalized_vacancies)

        return {
            "company_name": clean_comp or None,
            "company_normalized_key": norm_comp_key if clean_comp else None,
            "location": location,
            "contact_phone": phone,
            "contact_whatsapp": wa,
            "contact_email": email,
            "website_source": website_source,
            "walk_in_start_date": walk_in_start_date,
            "walk_in_end_date": walk_in_end_date,
            "walk_in_date_text": walk_in_date_text,
            "interview_time": interview_time,
            "immediate_joiners": immediate_joiners,
            "total_vacancies": len(normalized_vacancies),
            "total_openings": total_openings,
            "vacancies": normalized_vacancies,
            "primary_vacancy": primary_vacancy,
            "raw_ai_response": raw_ai_resp,
            "confidence_score": confidence,
            "warnings": warnings,
            "ai_used": ai_used,
            "ai_skipped": ai_skipped,
            "ai_provider_name": ai_provider_name
        }

    def process_raw_ingestion(
        self,
        raw_text: Optional[str] = None,
        image_bytes: Optional[bytes] = None,
        image_mime: Optional[str] = None,
        force_ai: bool = False
    ) -> Dict[str, Any]:
        """
        Backward-compatible single-job extraction wrapper around process_multi_job_ingestion.
        """
        multi_res = self.process_multi_job_ingestion(
            raw_text=raw_text,
            image_bytes=image_bytes,
            image_mime=image_mime,
            force_ai=force_ai
        )
        return {
            "extracted_data": multi_res["primary_vacancy"],
            "multi_job_data": multi_res,
            "raw_ai_response": multi_res["raw_ai_response"],
            "confidence_score": multi_res["confidence_score"],
            "warnings": multi_res["warnings"],
            "ai_used": multi_res["ai_used"],
            "ai_skipped": multi_res["ai_skipped"],
            "ai_provider_name": multi_res["ai_provider_name"]
        }
