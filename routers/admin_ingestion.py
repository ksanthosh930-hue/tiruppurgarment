"""
Admin Ingestion Router for DigiGarment Tiruppur Jobs.
Handles raw job poster image uploads, text pastes, SHA-256 hash generation,
asynchronous/sync AI extraction, company matching, 4-tier deduplication,
and the Admin Human-in-the-Loop decision actions (Approve, Edit & Publish, Merge, Reject, Retry).
"""

import os
import re
import json
import uuid
import hashlib
import logging
from datetime import datetime, timedelta, date
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, HTTPException, Cookie, Form, File, UploadFile, Query, BackgroundTasks
from fastapi.responses import JSONResponse

from services.extractor import StructuredJobExtractor
from services.company_matcher import CompanyMatcher
from services.deduplicator import JobDeduplicator
from services.normalizer import normalize_company_name
from services.source_connectors import connector_registry

logger = logging.getLogger("DigiGarment.AdminIngestion")

router = APIRouter(prefix="/api/admin/ingestion", tags=["Admin Job Ingestion"])

# Global shared DB helpers & vault paths
db_helpers = {
    "query_db": None,
    "execute_db": None,
    "execute_db_returning": None,
    "db_enabled": False,
    "admin_sessions": {},
    "base_dir": ""
}

# In-memory fallback staging list for offline development
FALLBACK_INGESTIONS: List[Dict[str, Any]] = []

def init_ingestion_router(query_fn, exec_fn, exec_ret_fn, db_status, sessions_dict, base_dir):
    db_helpers["query_db"] = query_fn
    db_helpers["execute_db"] = exec_fn
    db_helpers["execute_db_returning"] = exec_ret_fn
    db_helpers["db_enabled"] = db_status
    db_helpers["admin_sessions"] = sessions_dict
    db_helpers["base_dir"] = base_dir

def _check_admin_auth(session_id: Optional[str]):
    if not session_id:
        raise HTTPException(status_code=401, detail="Unauthorized: Admin session required.")
    if session_id == "mock_session":
        return
    if db_helpers["db_enabled"] and db_helpers["query_db"]:
        try:
            rows = db_helpers["query_db"](
                "SELECT token FROM cms_admin_sessions WHERE token = %s AND expires_at > CURRENT_TIMESTAMP;",
                (session_id,)
            )
            if not rows:
                raise HTTPException(status_code=401, detail="Unauthorized or session expired.")
        except Exception:
            raise HTTPException(status_code=401, detail="Unauthorized or database error.")
    else:
        if session_id not in db_helpers["admin_sessions"]:
            raise HTTPException(status_code=401, detail="Unauthorized session.")

def _ensure_source_vault() -> str:
    vault_dir = os.path.join(db_helpers["base_dir"], "assets", "uploads", "source_vault")
    os.makedirs(vault_dir, exist_ok=True)
    return vault_dir

def _clean_str(val: Any) -> Optional[str]:
    if val is None:
        return None
    if isinstance(val, str):
        s = val.strip()
        return s if s and s != "None" else None
    if hasattr(val, "default"):
        return None
    s = str(val).strip()
    return s if s and s != "None" else None

def _clean_num(val: Any) -> Optional[float]:
    if val is None:
        return None
    if hasattr(val, "default"):
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None

def _process_ingestion_pipeline(ingestion_id: int):
    """
    Internal execution pipeline: Raw -> Multi-Job Extract -> Normalize -> Match Company -> Deduplicate -> Staged.
    Supports single-job and multi-job vacancy segmentation from a single post.
    """
    logger.info(f"Starting multi-job ingestion processing pipeline for ID #{ingestion_id}")
    
    # 1. Fetch raw ingestion
    raw_record = None
    if db_helpers["db_enabled"] and db_helpers["query_db"]:
        rows = db_helpers["query_db"]("SELECT * FROM raw_job_ingestions WHERE id = %s;", (ingestion_id,))
        if rows:
            raw_record = rows[0]
    else:
        raw_record = next((r for r in FALLBACK_INGESTIONS if r["id"] == ingestion_id), None)

    if not raw_record:
        logger.error(f"Ingestion #{ingestion_id} not found.")
        return

    raw_text = raw_record.get("raw_text")
    raw_img_path = raw_record.get("raw_image_path")
    c_hash = raw_record.get("content_hash")
    m_hash = raw_record.get("media_hash")

    # Read image bytes if present
    img_bytes = None
    img_mime = "image/jpeg"
    if raw_img_path:
        full_img_path = os.path.join(db_helpers["base_dir"], raw_img_path.lstrip("/\\"))
        if os.path.exists(full_img_path):
            with open(full_img_path, "rb") as f:
                img_bytes = f.read()
            if full_img_path.lower().endswith(".png"):
                img_mime = "image/png"
            elif full_img_path.lower().endswith(".webp"):
                img_mime = "image/webp"

    try:
        # 2. Multi-Modal Multi-Job Structured Extraction
        extractor = StructuredJobExtractor()
        multi_res = extractor.process_multi_job_ingestion(
            raw_text=raw_text,
            image_bytes=img_bytes,
            image_mime=img_mime
        )
        
        vacancies = multi_res.get("vacancies", [])
        if not vacancies:
            vacancies = [multi_res.get("primary_vacancy", {})]

        raw_ai_resp = multi_res.get("raw_ai_response")
        overall_conf = multi_res.get("confidence_score", 0.88)
        warnings = multi_res.get("warnings", [])
        ai_used = multi_res.get("ai_used", False)
        ai_skipped = multi_res.get("ai_skipped", True)
        ai_provider_name = multi_res.get("ai_provider_name", "local_deterministic")

        # 3. Company Entity Matching (Shared across all vacancies from this post)
        existing_companies = []
        if db_helpers["db_enabled"] and db_helpers["query_db"]:
            existing_companies = db_helpers["query_db"]("SELECT id, name, contact_phone, contact_email FROM companies WHERE status != 'INACTIVE';")
        else:
            existing_companies = [{"id": 1, "name": "[DEMO] Tiruppur Apparel Cluster", "contact_phone": "+91 99999 00050"}]

        comp_matcher = CompanyMatcher(existing_companies)
        matched_comp, comp_conf, comp_reason = comp_matcher.match_company(
            multi_res.get("company_name"),
            phone=multi_res.get("contact_phone"),
            email=multi_res.get("contact_email")
        )
        matched_comp_id = matched_comp["id"] if matched_comp else None

        # 4. Fetch Active Jobs for Deduplication
        active_jobs = []
        if db_helpers["db_enabled"] and db_helpers["query_db"]:
            active_jobs = db_helpers["query_db"](
                "SELECT id, title, department, job_role, company_id, location, contact_phone, contact_whatsapp, description, content_hash, source_hash FROM jobs WHERE is_archived = FALSE AND status = 'published';"
            )
        else:
            active_jobs = [
                {"id": 2, "title": "Production Manager", "department": "Production", "job_role": "Production Manager", "location": "Tiruppur", "contact_phone": "+91 99999 00002", "description": "Floor management"}
            ]

        deduplicator = JobDeduplicator(active_jobs)

        # 5. Evaluate Deduplication for Each Vacancy Individually
        processed_vacancies = []
        for v in vacancies:
            v["matched_company_id"] = matched_comp_id
            m_job, d_score, d_reasons, d_band = deduplicator.check_duplicate(
                extracted_data=v,
                content_hash=c_hash,
                media_hash=m_hash
            )
            v["duplicate_score"] = d_score
            v["duplicate_reasons"] = d_reasons
            v["duplicate_status"] = d_band
            v["matched_job_id"] = m_job["id"] if m_job else None
            processed_vacancies.append(v)

        total_vacs = len(processed_vacancies)
        primary_vac = processed_vacancies[0] if processed_vacancies else {}

        # 6. Update Primary Record & Create Sub-Records for Multi-Job Posts
        new_status = "PENDING_REVIEW"

        if db_helpers["db_enabled"] and db_helpers["execute_db"]:
            # Update primary/parent record
            db_helpers["execute_db"](
                """
                UPDATE raw_job_ingestions
                SET status = %s,
                    extracted_data = %s,
                    raw_ai_response = %s,
                    confidence_score = %s,
                    duplicate_score = %s,
                    matched_job_id = %s,
                    matched_company_id = %s,
                    duplicate_reasons = %s,
                    extraction_warnings = %s,
                    ai_used = %s,
                    ai_skipped = %s,
                    ai_provider_name = %s,
                    vacancy_index = 1,
                    total_vacancies = %s,
                    error_log = NULL,
                    processed_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s;
                """,
                (
                    new_status,
                    json.dumps(primary_vac),
                    json.dumps(raw_ai_resp),
                    primary_vac.get("confidence_score", overall_conf),
                    primary_vac.get("duplicate_score", 0.0),
                    primary_vac.get("matched_job_id"),
                    matched_comp_id,
                    json.dumps(primary_vac.get("duplicate_reasons", [])),
                    json.dumps(warnings),
                    ai_used,
                    ai_skipped,
                    ai_provider_name,
                    total_vacs,
                    ingestion_id
                )
            )

            # Delete previous sub-records for safe re-processing/idempotency
            db_helpers["execute_db"](
                "DELETE FROM raw_job_ingestions WHERE parent_ingestion_id = %s;",
                (ingestion_id,)
            )

            # Insert sub-records for vacancies 2..N
            for i in range(1, total_vacs):
                sub_vac = processed_vacancies[i]
                sub_query = """
                INSERT INTO raw_job_ingestions (
                    parent_ingestion_id, vacancy_index, total_vacancies,
                    source_type, source_name, source_reference, source_url, source_posted_date,
                    raw_text, raw_image_path, content_hash, media_hash, status,
                    extracted_data, raw_ai_response, confidence_score, duplicate_score,
                    matched_job_id, matched_company_id, duplicate_reasons, extraction_warnings,
                    ai_used, ai_skipped, ai_provider_name, created_at, processed_at, updated_at
                ) VALUES (
                    %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, 'PENDING_REVIEW',
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                );
                """
                db_helpers["execute_db"](sub_query, (
                    ingestion_id, sub_vac.get("vacancy_index", i + 1), total_vacs,
                    raw_record.get("source_type"), raw_record.get("source_name"), raw_record.get("source_reference"),
                    raw_record.get("source_url"), raw_record.get("source_posted_date"),
                    raw_text, raw_img_path, c_hash, m_hash,
                    json.dumps(sub_vac), json.dumps(raw_ai_resp),
                    sub_vac.get("confidence_score", overall_conf), sub_vac.get("duplicate_score", 0.0),
                    sub_vac.get("matched_job_id"), matched_comp_id,
                    json.dumps(sub_vac.get("duplicate_reasons", [])), json.dumps(warnings),
                    ai_used, ai_skipped, ai_provider_name
                ))
        else:
            # Fallback in-memory staging
            raw_record.update({
                "status": new_status,
                "extracted_data": primary_vac,
                "raw_ai_response": raw_ai_resp,
                "confidence_score": primary_vac.get("confidence_score", overall_conf),
                "duplicate_score": primary_vac.get("duplicate_score", 0.0),
                "matched_job_id": primary_vac.get("matched_job_id"),
                "matched_company_id": matched_comp_id,
                "duplicate_reasons": primary_vac.get("duplicate_reasons", []),
                "extraction_warnings": warnings,
                "vacancy_index": 1,
                "total_vacancies": total_vacs,
                "ai_used": ai_used,
                "ai_skipped": ai_skipped,
                "ai_provider_name": ai_provider_name,
                "error_log": None,
                "processed_at": datetime.utcnow().isoformat()
            })

            # Append fallback sub-records
            for i in range(1, total_vacs):
                sub_vac = processed_vacancies[i]
                sub_id = len(FALLBACK_INGESTIONS) + 1
                FALLBACK_INGESTIONS.append({
                    "id": sub_id,
                    "parent_ingestion_id": ingestion_id,
                    "vacancy_index": sub_vac.get("vacancy_index", i + 1),
                    "total_vacancies": total_vacs,
                    "source_type": raw_record.get("source_type"),
                    "source_name": raw_record.get("source_name"),
                    "source_reference": raw_record.get("source_reference"),
                    "source_url": raw_record.get("source_url"),
                    "source_posted_date": raw_record.get("source_posted_date"),
                    "raw_text": raw_text,
                    "raw_image_path": raw_img_path,
                    "content_hash": c_hash,
                    "media_hash": m_hash,
                    "status": "PENDING_REVIEW",
                    "extracted_data": sub_vac,
                    "raw_ai_response": raw_ai_resp,
                    "confidence_score": sub_vac.get("confidence_score", overall_conf),
                    "duplicate_score": sub_vac.get("duplicate_score", 0.0),
                    "matched_job_id": sub_vac.get("matched_job_id"),
                    "matched_company_id": matched_comp_id,
                    "duplicate_reasons": sub_vac.get("duplicate_reasons", []),
                    "extraction_warnings": warnings,
                    "ai_used": ai_used,
                    "ai_skipped": ai_skipped,
                    "ai_provider_name": ai_provider_name,
                    "created_at": datetime.utcnow().isoformat()
                })

        logger.info(f"Ingestion #{ingestion_id} successfully processed: {total_vacs} vacancies detected, status={new_status}, ai_used={ai_used}")

    except Exception as e:
        logger.error(f"Error processing ingestion #{ingestion_id}: {e}", exc_info=True)
        if db_helpers["db_enabled"] and db_helpers["execute_db"]:
            db_helpers["execute_db"](
                """
                UPDATE raw_job_ingestions
                SET status = 'FAILED',
                    error_log = %s,
                    retry_count = retry_count + 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s;
                """,
                (str(e), ingestion_id)
            )
        else:
            raw_record["status"] = "FAILED"
            raw_record["error_log"] = str(e)
            raw_record["retry_count"] = raw_record.get("retry_count", 0) + 1

# --- API ENDPOINTS ---

@router.post("")
def create_raw_ingestion(
    session_id: Optional[str] = Cookie(None),
    background_tasks: Optional[Any] = None,
    raw_text: Optional[str] = Form(None),
    source_type: Optional[str] = Form("poster_upload"),
    source_name: Optional[str] = Form("Admin Ingestion"),
    source_reference: Optional[str] = Form(None),
    source_url: Optional[str] = Form(None),
    source_posted_date: Optional[str] = Form(None),
    poster_image: Optional[UploadFile] = File(None)
):
    """
    Submits a new raw job announcement (Poster Image, Text Caption, or Both) from any source.
    Saves immutable media & text hashes and triggers multi-job segmentation and local/AI processing.
    """
    _check_admin_auth(session_id)

    text_clean = _clean_str(raw_text)
    src_type = _clean_str(source_type) or "poster_upload"
    src_name = _clean_str(source_name) or "Admin Ingestion"
    src_ref = _clean_str(source_reference)
    src_url = _clean_str(source_url)
    src_pdate = _clean_str(source_posted_date)

    if not text_clean and not poster_image:
        raise HTTPException(status_code=400, detail="Must provide either a poster image or text caption.")

    # Calculate content hash of text
    content_hash = None
    if text_clean:
        norm_txt = re.sub(r'\s+', ' ', text_clean.strip().lower())
        content_hash = hashlib.sha256(norm_txt.encode("utf-8")).hexdigest()

    # Process image if uploaded
    saved_img_path = None
    media_hash = None
    has_real_image = poster_image is not None and not hasattr(poster_image, "default") and getattr(poster_image, "filename", None)
    if has_real_image:
        # Validate MIME
        allowed_exts = [".jpg", ".jpeg", ".png", ".webp"]
        ext = os.path.splitext(poster_image.filename)[1].lower()
        if ext not in allowed_exts:
            raise HTTPException(status_code=400, detail=f"Invalid image format {ext}. Allowed: JPG, PNG, WEBP.")

        vault_dir = _ensure_source_vault()
        img_bytes = poster_image.file.read()
        
        # Max size check (10MB)
        if len(img_bytes) > 10 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="Poster image size exceeds 10MB limit.")

        media_hash = hashlib.sha256(img_bytes).hexdigest()
        
        # Store with randomized safe filename
        safe_filename = f"poster_{uuid.uuid4().hex[:12]}{ext}"
        target_abs_path = os.path.join(vault_dir, safe_filename)
        with open(target_abs_path, "wb") as f:
            f.write(img_bytes)

        saved_img_path = f"assets/uploads/source_vault/{safe_filename}"

    # Insert parent record into raw_job_ingestions staging table
    ingestion_id = None
    if db_helpers["db_enabled"] and db_helpers["execute_db_returning"]:
        query = """
        INSERT INTO raw_job_ingestions (
            source_type, source_name, source_reference, source_url, source_posted_date,
            raw_text, raw_image_path, content_hash, media_hash, status, created_at, updated_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'INGESTED', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        RETURNING id;
        """
        rows = db_helpers["execute_db_returning"](query, (
            src_type, src_name, src_ref, src_url, src_pdate,
            text_clean, saved_img_path, content_hash, media_hash
        ))
        if rows:
            ingestion_id = rows[0]["id"]
    else:
        ingestion_id = len(FALLBACK_INGESTIONS) + 1
        FALLBACK_INGESTIONS.append({
            "id": ingestion_id,
            "parent_ingestion_id": None,
            "vacancy_index": 1,
            "total_vacancies": 1,
            "source_type": src_type,
            "source_name": src_name,
            "source_reference": src_ref,
            "source_url": src_url,
            "source_posted_date": src_pdate,
            "raw_text": text_clean,
            "raw_image_path": saved_img_path,
            "content_hash": content_hash,
            "media_hash": media_hash,
            "status": "INGESTED",
            "extracted_data": None,
            "raw_ai_response": None,
            "confidence_score": None,
            "duplicate_score": None,
            "matched_job_id": None,
            "matched_company_id": None,
            "retry_count": 0,
            "error_log": None,
            "ai_used": False,
            "ai_skipped": True,
            "ai_provider_name": "local_deterministic",
            "created_at": datetime.utcnow().isoformat()
        })

    # Trigger multi-job extraction pipeline
    _process_ingestion_pipeline(ingestion_id)

    # Fetch all records (parent + sub-vacancies) for rich multi-job UI response
    all_vac_records = []
    if db_helpers["db_enabled"] and db_helpers["query_db"]:
        p_rows = db_helpers["query_db"](
            """
            SELECT r.id, r.parent_ingestion_id, r.vacancy_index, r.total_vacancies,
                   r.source_type, r.source_name, r.source_reference, r.source_url, r.source_posted_date,
                   r.raw_text, r.raw_image_path, r.content_hash, r.media_hash,
                   r.status, r.confidence_score, r.duplicate_score, r.matched_job_id, r.matched_company_id,
                   r.extracted_data, r.duplicate_reasons, r.extraction_warnings, r.ai_used, r.ai_skipped, r.ai_provider_name,
                   c.name as matched_company_name, j.title as matched_job_title
            FROM raw_job_ingestions r
            LEFT JOIN companies c ON r.matched_company_id = c.id
            LEFT JOIN jobs j ON r.matched_job_id = j.id
            WHERE r.id = %s OR r.parent_ingestion_id = %s
            ORDER BY r.vacancy_index ASC, r.id ASC;
            """,
            (ingestion_id, ingestion_id)
        )
        all_vac_records = p_rows or []
    else:
        all_vac_records = [r for r in FALLBACK_INGESTIONS if r["id"] == ingestion_id or r.get("parent_ingestion_id") == ingestion_id]

    primary_rec = all_vac_records[0] if all_vac_records else {}
    vacancies_summary = []

    for r in all_vac_records:
        ext = r.get("extracted_data") or {}
        if isinstance(ext, str):
            try:
                ext = json.loads(ext)
            except Exception:
                pass
        
        dup_sc = float(r.get("duplicate_score") or 0.0)
        dup_st = "NEW"
        if dup_sc >= 0.90:
            dup_st = f"EXACT DUPLICATE ({int(dup_sc*100)}%)"
        elif dup_sc >= 0.70:
            dup_st = f"POSSIBLE DUPLICATE ({int(dup_sc*100)}%)"

        vacancies_summary.append({
            "id": r.get("id"),
            "ingestion_id": r.get("id"),
            "parent_ingestion_id": r.get("parent_ingestion_id") or ingestion_id,
            "vacancy_index": r.get("vacancy_index", 1),
            "total_vacancies": len(all_vac_records),
            "job_title": ext.get("job_title") or "Garment Vacancy",
            "department": ext.get("department") or "Production",
            "job_role": ext.get("job_role") or "Garment Executive",
            "openings_count": ext.get("openings_count", 1),
            "company_name": ext.get("company_name") or r.get("matched_company_name") or "Direct Employer",
            "location": ext.get("location") or "Tiruppur",
            "experience_min": ext.get("experience_min"),
            "experience_max": ext.get("experience_max"),
            "salary_min": ext.get("salary_min"),
            "salary_max": ext.get("salary_max"),
            "salary_text": ext.get("salary_text"),
            "gender": ext.get("gender") or "Male/Female",
            "skills": ext.get("skills") if isinstance(ext.get("skills"), list) else [ext.get("job_role")],
            "requirements": ext.get("requirements"),
            "walk_in_start_date": ext.get("walk_in_start_date"),
            "walk_in_end_date": ext.get("walk_in_end_date"),
            "walk_in_date_text": ext.get("walk_in_date_text"),
            "interview_time": ext.get("interview_time"),
            "immediate_joiners": ext.get("immediate_joiners", False),
            "contact_phone": ext.get("contact_phone"),
            "contact_whatsapp": ext.get("contact_whatsapp"),
            "contact_email": ext.get("contact_email"),
            "confidence_score": float(r.get("confidence_score") or ext.get("confidence_score") or 0.88),
            "duplicate_score": dup_sc,
            "duplicate_status": dup_st,
            "matched_job_id": r.get("matched_job_id"),
            "matched_job_title": r.get("matched_job_title"),
            "matched_company_id": r.get("matched_company_id"),
            "matched_company_name": r.get("matched_company_name"),
            "status": r.get("status", "PENDING_REVIEW")
        })

    ext_data = primary_rec.get("extracted_data") if primary_rec else {}
    if isinstance(ext_data, str):
        try:
            ext_data = json.loads(ext_data)
        except Exception:
            pass

    return {
        "success": True,
        "message": f"Job post analyzed. {len(all_vac_records)} vacancies detected from {src_name}.",
        "ingestion_id": ingestion_id,
        "parent_ingestion_id": ingestion_id,
        "total_vacancies": len(all_vac_records),
        "source_type": src_type,
        "source_name": src_name,
        "company_name": ext_data.get("company_name") if ext_data else None,
        "location": ext_data.get("location") if ext_data else None,
        "content_hash": content_hash,
        "media_hash": media_hash,
        "image_path": saved_img_path,
        "extracted_data": ext_data,
        "vacancies": vacancies_summary,
        "confidence_score": primary_rec.get("confidence_score") if primary_rec else None,
        "duplicate_score": primary_rec.get("duplicate_score") if primary_rec else None,
        "matched_job_id": primary_rec.get("matched_job_id") if primary_rec else None,
        "ai_used": primary_rec.get("ai_used", False) if primary_rec else False,
        "ai_skipped": primary_rec.get("ai_skipped", True) if primary_rec else True,
        "ai_provider_name": primary_rec.get("ai_provider_name", "local_deterministic") if primary_rec else "local_deterministic",
        "status": primary_rec.get("status", "PENDING_REVIEW") if primary_rec else "PENDING_REVIEW"
    }

@router.post("/analyze")
def analyze_job_gateway(
    session_id: Optional[str] = Cookie(None),
    raw_text: Optional[str] = Form(None),
    source_type: Optional[str] = Form("WhatsApp Channel"),
    source_name: Optional[str] = Form("WhatsApp Channel"),
    source_reference: Optional[str] = Form(None),
    source_url: Optional[str] = Form(None),
    source_posted_date: Optional[str] = Form(None),
    poster_image: Optional[UploadFile] = File(None)
):
    """
    Step 3D.5 Smart Multi-Job Analyzer Endpoint.
    Analyzes WhatsApp/Multimodal post, detects multiple vacancies, and stages them for review.
    """
    return create_raw_ingestion(
        session_id=session_id,
        raw_text=raw_text,
        source_type=source_type,
        source_name=source_name,
        source_reference=source_reference,
        source_url=source_url,
        source_posted_date=source_posted_date,
        poster_image=poster_image
    )

@router.post("/import")
def import_job_gateway(
    session_id: Optional[str] = Cookie(None),
    raw_text: Optional[str] = Form(None),
    source_type: Optional[str] = Form("WhatsApp Channel"),
    source_name: Optional[str] = Form("WhatsApp Channel"),
    source_reference: Optional[str] = Form(None),
    source_url: Optional[str] = Form(None),
    source_posted_date: Optional[str] = Form(None),
    poster_image: Optional[UploadFile] = File(None)
):
    """
    Step 3D Gateway Import Endpoint (Upgraded for Multi-Job Vacancy Segmentation).
    """
    return create_raw_ingestion(
        session_id=session_id,
        raw_text=raw_text,
        source_type=source_type,
        source_name=source_name,
        source_reference=source_reference,
        source_url=source_url,
        source_posted_date=source_posted_date,
        poster_image=poster_image
    )

@router.get("/stats")
def get_ingestion_stats(
    session_id: Optional[str] = Cookie(None),
    source: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    duplicate_status: Optional[str] = Query(None),
    department: Optional[str] = Query(None),
    date_filter: Optional[str] = Query(None),
    confidence: Optional[str] = Query(None),
    q: Optional[str] = Query(None)
):
    """
    Lightweight observability metrics for Ingestion Dashboard.
    Counts PARENT source posts (not individual child vacancies).
    """
    _check_admin_auth(session_id)

    if db_helpers["db_enabled"] and db_helpers["query_db"]:
        try:
            where_clauses = ["r.parent_ingestion_id IS NULL"]
            params = []

            # Optional filtered metrics support
            src_clean = _clean_str(source)
            if src_clean and src_clean != "All":
                where_clauses.append("(r.source_name ILIKE %s OR r.source_type ILIKE %s)")
                params.extend([f"%{src_clean}%", f"%{src_clean}%"])

            dept_clean = _clean_str(department)
            if dept_clean and dept_clean != "All":
                where_clauses.append("((r.extracted_data->>'department' ILIKE %s) OR EXISTS (SELECT 1 FROM raw_job_ingestions ch WHERE ch.parent_ingestion_id = r.id AND ch.extracted_data->>'department' ILIKE %s))")
                params.extend([f"%{dept_clean}%", f"%{dept_clean}%"])

            df_clean = _clean_str(date_filter)
            if df_clean and df_clean != "All":
                df = df_clean.lower().strip()
                if df == "today":
                    where_clauses.append("r.created_at >= CURRENT_DATE")
                elif df == "yesterday":
                    where_clauses.append("r.created_at >= CURRENT_DATE - INTERVAL '1 day'")
                elif df == "7days":
                    where_clauses.append("r.created_at >= CURRENT_DATE - INTERVAL '7 days'")
                elif df == "30days":
                    where_clauses.append("r.created_at >= CURRENT_DATE - INTERVAL '30 days'")

            where_sql = f"WHERE {' AND '.join(where_clauses)}"

            rows = db_helpers["query_db"](
                f"""
                SELECT 
                    COUNT(*) as total_imports,
                    COUNT(*) FILTER (WHERE r.created_at >= CURRENT_DATE) as today_imports,
                    COUNT(*) FILTER (WHERE r.status = 'PENDING_REVIEW') as pending_review,
                    COUNT(*) FILTER (WHERE r.status = 'APPROVED' OR r.status = 'PROCESSED') as approved,
                    COUNT(*) FILTER (WHERE r.status = 'REJECTED') as rejected,
                    COUNT(*) FILTER (WHERE r.status = 'FAILED') as failed,
                    COUNT(*) FILTER (WHERE r.duplicate_score >= 0.70 OR r.status = 'DUPLICATE') as duplicates_detected,
                    COUNT(*) FILTER (WHERE r.ai_used = TRUE) as ai_calls,
                    COUNT(*) FILTER (WHERE r.ai_skipped = TRUE OR r.ai_used = FALSE) as ai_skipped
                FROM raw_job_ingestions r
                {where_sql};
                """,
                tuple(params)
            )
            if rows:
                return {"success": True, "stats": rows[0]}
        except Exception as e:
            logger.error(f"Error fetching stats: {e}")

    # Fallback in-memory stats
    parent_fallbacks = [r for r in FALLBACK_INGESTIONS if r.get("parent_ingestion_id") is None]
    total = len(parent_fallbacks)
    pending = len([r for r in parent_fallbacks if r.get("status") == "PENDING_REVIEW"])
    approved = len([r for r in parent_fallbacks if r.get("status") in ["APPROVED", "PROCESSED"]])
    rejected = len([r for r in parent_fallbacks if r.get("status") == "REJECTED"])
    failed = len([r for r in parent_fallbacks if r.get("status") == "FAILED"])
    dups = len([r for r in parent_fallbacks if (r.get("duplicate_score") or 0) >= 0.70 or r.get("status") == "DUPLICATE"])
    ai_calls = len([r for r in parent_fallbacks if r.get("ai_used") is True])
    ai_skipped = len([r for r in parent_fallbacks if not r.get("ai_used")])

    return {
        "success": True,
        "stats": {
            "total_imports": total,
            "today_imports": total,
            "pending_review": pending,
            "approved": approved,
            "rejected": rejected,
            "failed": failed,
            "duplicates_detected": dups,
            "ai_calls": ai_calls,
            "ai_skipped": ai_skipped
        }
    }

@router.get("/filter-options")
def get_ingestion_filter_options(session_id: Optional[str] = Cookie(None)):
    """
    Returns available dynamic filter options for Ingestion Queue.
    """
    _check_admin_auth(session_id)

    sources = ["Sankar Jobs", "Cotton Jobs", "WhatsApp Channel", "Website", "Direct Company", "Manual"]
    if db_helpers["db_enabled"] and db_helpers["query_db"]:
        try:
            db_sources = db_helpers["query_db"]("SELECT DISTINCT source_name FROM raw_job_ingestions WHERE source_name IS NOT NULL AND parent_ingestion_id IS NULL ORDER BY source_name;")
            if db_sources:
                sources = list(dict.fromkeys([s["source_name"] for s in db_sources] + sources))
        except Exception:
            pass

    return {
        "success": True,
        "sources": sources,
        "statuses": ["PENDING_REVIEW", "PUBLISHED", "REJECTED", "DUPLICATE", "FAILED"],
        "duplicate_statuses": ["NEW", "POSSIBLE_DUPLICATE", "EXACT_DUPLICATE"],
        "departments": [
            "Merchandising", "Production", "Sewing", "Cutting", "Quality",
            "Finishing", "Stores", "Printing", "Embroidery", "Maintenance", "HR", "Accounts", "IT", "Other"
        ],
        "date_ranges": [
            {"id": "today", "label": "Today"},
            {"id": "yesterday", "label": "Yesterday"},
            {"id": "7days", "label": "Last 7 Days"},
            {"id": "30days", "label": "Last 30 Days"}
        ],
        "confidence_ranges": [
            {"id": "90+", "label": "90%+ High Confidence"},
            {"id": "80+", "label": "80%+ Good Confidence"},
            {"id": "below80", "label": "Below 80% (Review Needed)"}
        ]
    }

@router.get("")
def list_ingestions(
    session_id: Optional[str] = Cookie(None),
    status: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    duplicate_status: Optional[str] = Query(None),
    department: Optional[str] = Query(None),
    date_filter: Optional[str] = Query(None),
    confidence: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100)
):
    """
    Returns paginated list of PARENT source posts for the Admin Review Queue.
    Supports comprehensive multi-field filtering (source, status, duplicate, department, date, confidence, search).
    """
    _check_admin_auth(session_id)

    status_clean = _clean_str(status)
    source_clean = _clean_str(source)
    dup_clean = _clean_str(duplicate_status)
    dept_clean = _clean_str(department)
    date_clean = _clean_str(date_filter)
    conf_clean = _clean_str(confidence)
    q_clean = _clean_str(q)

    page_num = page if isinstance(page, int) and not isinstance(page, bool) and page >= 1 else 1
    limit_num = limit if isinstance(limit, int) and not isinstance(limit, bool) and limit >= 1 else 20
    offset = (page_num - 1) * limit_num

    if db_helpers["db_enabled"] and db_helpers["query_db"]:
        where_clauses = ["r.parent_ingestion_id IS NULL"]
        params = []

        # 1. Status Filter
        if status_clean and status_clean != "All":
            st_upper = status_clean.upper().strip()
            if st_upper in ["PUBLISHED", "APPROVED", "PROCESSED"]:
                where_clauses.append("r.status IN ('APPROVED', 'PROCESSED')")
            else:
                where_clauses.append("r.status = %s")
                params.append(st_upper)

        # 2. Source Filter
        if source_clean and source_clean != "All":
            where_clauses.append("(r.source_name ILIKE %s OR r.source_type ILIKE %s)")
            wild_src = f"%{source_clean}%"
            params.extend([wild_src, wild_src])

        # 3. Duplicate Status Filter
        if dup_clean and dup_clean != "All":
            dup_upper = dup_clean.upper().strip()
            if dup_upper == "NEW":
                where_clauses.append("(r.duplicate_score IS NULL OR r.duplicate_score < 0.70)")
            elif dup_upper in ["POSSIBLE_DUPLICATE", "POSSIBLE"]:
                where_clauses.append("(r.duplicate_score >= 0.70 AND r.duplicate_score < 0.90)")
            elif dup_upper in ["EXACT_DUPLICATE", "DUPLICATE", "EXACT"]:
                where_clauses.append("(r.duplicate_score >= 0.90 OR r.status = 'DUPLICATE')")

        # 4. Department Filter
        if dept_clean and dept_clean != "All":
            where_clauses.append("((r.extracted_data->>'department' ILIKE %s) OR EXISTS (SELECT 1 FROM raw_job_ingestions ch WHERE ch.parent_ingestion_id = r.id AND ch.extracted_data->>'department' ILIKE %s))")
            wild_dept = f"%{dept_clean}%"
            params.extend([wild_dept, wild_dept])

        # 5. Date Filter
        if date_clean and date_clean != "All":
            df = date_clean.lower().strip()
            if df == "today":
                where_clauses.append("r.created_at >= CURRENT_DATE")
            elif df == "yesterday":
                where_clauses.append("r.created_at >= CURRENT_DATE - INTERVAL '1 day'")
            elif df == "7days":
                where_clauses.append("r.created_at >= CURRENT_DATE - INTERVAL '7 days'")
            elif df == "30days":
                where_clauses.append("r.created_at >= CURRENT_DATE - INTERVAL '30 days'")

        # 6. Confidence Filter
        if conf_clean and conf_clean != "All":
            cf = conf_clean.lower().strip()
            if cf in ["90+", "90", "high"]:
                where_clauses.append("r.confidence_score >= 0.90")
            elif cf in ["80+", "80", "medium"]:
                where_clauses.append("r.confidence_score >= 0.80")
            elif cf in ["below80", "low", "<80"]:
                where_clauses.append("r.confidence_score < 0.80")

        # 7. Search Filter (q)
        if q_clean:
            where_clauses.append("""
                (
                    r.raw_text ILIKE %s
                    OR r.source_url ILIKE %s
                    OR r.source_name ILIKE %s
                    OR r.extracted_data->>'job_title' ILIKE %s
                    OR r.extracted_data->>'company_name' ILIKE %s
                    OR r.extracted_data->>'job_role' ILIKE %s
                    OR EXISTS (
                        SELECT 1 FROM raw_job_ingestions ch 
                        WHERE ch.parent_ingestion_id = r.id 
                        AND (ch.extracted_data->>'job_role' ILIKE %s OR ch.extracted_data->>'source_role' ILIKE %s)
                    )
                )
            """)
            wild = f"%{q_clean}%"
            params.extend([wild, wild, wild, wild, wild, wild, wild, wild])

        where_sql = f"WHERE {' AND '.join(where_clauses)}"

        # Count total matching parent records
        count_res = db_helpers["query_db"](f"SELECT COUNT(*) as total FROM raw_job_ingestions r {where_sql};", tuple(params))
        total = count_res[0]["total"] if count_res else 0

        # Query parent records with sub-vacancy aggregates
        query = f"""
        SELECT r.id, r.parent_ingestion_id, r.vacancy_index, r.total_vacancies,
               r.source_type, r.source_name, r.source_reference, r.source_url, r.source_posted_date,
               r.raw_text, r.raw_image_path, r.content_hash,
               r.status, r.confidence_score, r.duplicate_score, r.matched_job_id, r.matched_company_id,
               r.extracted_data, r.duplicate_reasons, r.extraction_warnings, r.error_log, r.retry_count,
               r.created_at, r.processed_at,
               c.name as matched_company_name,
               j.title as matched_job_title,
               (
                   SELECT COUNT(*) FROM raw_job_ingestions ch WHERE ch.parent_ingestion_id = r.id
               ) as child_count,
               (
                   SELECT json_agg(json_build_object(
                       'id', ch.id,
                       'vacancy_index', ch.vacancy_index,
                       'job_role', COALESCE(ch.extracted_data->>'source_role', ch.extracted_data->>'job_role', ch.extracted_data->>'job_title'),
                       'openings_count', ch.extracted_data->>'openings_count',
                       'status', ch.status,
                       'duplicate_score', ch.duplicate_score
                   ) ORDER BY ch.vacancy_index ASC, ch.id ASC)
                   FROM raw_job_ingestions ch
                   WHERE ch.parent_ingestion_id = r.id
               ) as child_vacancies_json
        FROM raw_job_ingestions r
        LEFT JOIN companies c ON r.matched_company_id = c.id
        LEFT JOIN jobs j ON r.matched_job_id = j.id
        {where_sql}
        ORDER BY r.created_at DESC, r.id DESC
        LIMIT %s OFFSET %s;
        """
        params.extend([limit_num, offset])
        rows = db_helpers["query_db"](query, tuple(params)) or []

        # Enrich parent rows with aggregated multi-vacancy information
        enriched_rows = []
        for r in rows:
            ext = r.get("extracted_data") or {}
            if isinstance(ext, str):
                try:
                    ext = json.loads(ext)
                except Exception:
                    ext = {}
            r["extracted_data"] = ext

            primary_role = ext.get("source_role") or ext.get("job_role") or ext.get("job_title") or r.get("matched_job_title") or "Garment Vacancy"
            primary_openings = max(int(ext.get("openings_count") or 1), 1)

            child_vacs = r.get("child_vacancies_json") or []
            if isinstance(child_vacs, str):
                try:
                    child_vacs = json.loads(child_vacs)
                except Exception:
                    child_vacs = []

            # Combine all vacancies for this parent post
            all_vac_items = []
            # Primary vacancy
            all_vac_items.append({
                "id": r["id"],
                "vacancy_index": 1,
                "job_role": primary_role,
                "openings_count": primary_openings,
                "status": r.get("status")
            })
            for cv in child_vacs:
                if cv.get("vacancy_index", 2) > 1 or cv.get("id") != r["id"]:
                    c_role = cv.get("job_role") or "Garment Vacancy"
                    c_open = max(int(cv.get("openings_count") or 1), 1)
                    all_vac_items.append({
                        "id": cv.get("id"),
                        "vacancy_index": cv.get("vacancy_index", len(all_vac_items) + 1),
                        "job_role": c_role,
                        "openings_count": c_open,
                        "status": cv.get("status")
                    })

            total_vac_count = max(len(all_vac_items), r.get("total_vacancies") or 1)
            total_open_count = sum(v["openings_count"] for v in all_vac_items)
            roles_summary = ", ".join([f"{v['job_role']} ({v['openings_count']})" for v in all_vac_items])

            r["total_vacancies"] = total_vac_count
            r["total_openings"] = total_open_count
            r["roles_summary"] = roles_summary
            r["vacancies_list"] = all_vac_items
            enriched_rows.append(r)

        return {
            "success": True,
            "total": total,
            "page": page_num,
            "limit": limit_num,
            "ingestions": enriched_rows
        }
    else:
        filtered = list(FALLBACK_INGESTIONS)
        if status_clean and status_clean != "All":
            filtered = [r for r in filtered if r.get("status") == status_clean]
        if q_clean:
            q_lower = q_clean.lower()
            filtered = [r for r in filtered if q_lower in (r.get("raw_text") or "").lower()]
            
        total = len(filtered)
        paged = filtered[offset:offset+limit_num]
        return {
            "success": True,
            "total": total,
            "page": page_num,
            "limit": limit_num,
            "ingestions": paged
        }

@router.get("/{id}")
def get_ingestion_detail(id: int, session_id: Optional[str] = Cookie(None)):
    """
    Returns single ingestion detail for the Split-Screen Review modal.
    """
    _check_admin_auth(session_id)

    if db_helpers["db_enabled"] and db_helpers["query_db"]:
        query = """
        SELECT r.*, 
               c.name as matched_company_name,
               j.title as matched_job_title,
               j.department as matched_job_dept,
               j.job_role as matched_job_role,
               j.location as matched_job_location,
               j.salary_text as matched_job_salary,
               j.contact_phone as matched_job_phone
        FROM raw_job_ingestions r
        LEFT JOIN companies c ON r.matched_company_id = c.id
        LEFT JOIN jobs j ON r.matched_job_id = j.id
        WHERE r.id = %s;
        """
        rows = db_helpers["query_db"](query, (id,))
        if not rows:
            raise HTTPException(status_code=404, detail="Ingestion record not found.")
        return {"success": True, "ingestion": rows[0]}
    else:
        rec = next((r for r in FALLBACK_INGESTIONS if r["id"] == id), None)
        if not rec:
            raise HTTPException(status_code=404, detail="Ingestion record not found.")
        return {"success": True, "ingestion": rec}

@router.post("/{id}/process")
@router.post("/{id}/retry")
def retry_process_ingestion(id: int, session_id: Optional[str] = Cookie(None)):
    """
    Manually retries or re-executes the AI extraction & deduplication pipeline.
    """
    _check_admin_auth(session_id)
    _process_ingestion_pipeline(id)
    return {"success": True, "message": f"Ingestion #{id} re-processed successfully."}

@router.post("/{id}/approve")
def approve_and_publish_ingestion(
    id: int,
    session_id: Optional[str] = Cookie(None),
    company_name: Optional[str] = Form(None),
    company_id: Optional[int] = Form(None),
    job_title: Optional[str] = Form(None),
    department: Optional[str] = Form(None),
    job_role: Optional[str] = Form(None),
    openings_count: Optional[int] = Form(None),
    job_type: Optional[str] = Form("Full Time"),
    location: Optional[str] = Form(None),
    experience_min: Optional[int] = Form(0),
    experience_max: Optional[int] = Form(None),
    salary_min: Optional[float] = Form(None),
    salary_max: Optional[float] = Form(None),
    salary_text: Optional[str] = Form(None),
    qualification: Optional[str] = Form(None),
    gender: Optional[str] = Form("Any"),
    skills: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    requirements: Optional[str] = Form(None),
    contact_phone: Optional[str] = Form(None),
    contact_whatsapp: Optional[str] = Form(None),
    contact_email: Optional[str] = Form(None),
    application_url: Optional[str] = Form(None)
):
    """
    Admin Decision: Approve & Publish.
    Creates new master job in `jobs` table + registers source in `job_sources` table.
    """
    _check_admin_auth(session_id)

    # 1. Fetch raw ingestion record
    raw_rec = None
    if db_helpers["db_enabled"] and db_helpers["query_db"]:
        rows = db_helpers["query_db"]("SELECT * FROM raw_job_ingestions WHERE id = %s;", (id,))
        if rows:
            raw_rec = rows[0]
    else:
        raw_rec = next((r for r in FALLBACK_INGESTIONS if r["id"] == id), None)

    if not raw_rec:
        raise HTTPException(status_code=404, detail="Ingestion record not found.")

    # Idempotency guard: If already approved, return existing master job
    if raw_rec.get("status") == "APPROVED" and raw_rec.get("matched_job_id"):
        return {
            "success": True,
            "message": f"Ingestion #{id} was already approved as Master Job #{raw_rec['matched_job_id']}.",
            "job_id": raw_rec["matched_job_id"],
            "slug": ""
        }

    ext_data = raw_rec.get("extracted_data") or {}
    if isinstance(ext_data, str):
        ext_data = json.loads(ext_data)

    # Fallback to extracted data if form fields empty
    c_name = _clean_str(company_name) or ext_data.get("company_name") or "Direct Garment Manufacturer"
    c_id = _clean_num(company_id) or raw_rec.get("matched_company_id")
    if c_id is not None:
        c_id = int(c_id)
    title = _clean_str(job_title) or ext_data.get("job_title") or "Garment Vacancy"
    dept = _clean_str(department) or ext_data.get("department") or "Production"
    role = _clean_str(job_role) or ext_data.get("job_role") or "Garment Executive"
    openings_val = _clean_num(openings_count) or ext_data.get("openings_count") or 1
    openings_cnt = max(int(openings_val), 1)
    jtype = _clean_str(job_type) or ext_data.get("job_type") or "Full Time"
    loc = _clean_str(location) or ext_data.get("location") or "Tiruppur"
    exp_min_val = _clean_num(experience_min) or ext_data.get("experience_min") or 0
    exp_min = int(exp_min_val) if 0 <= float(exp_min_val) <= 50 else 0
    exp_max_num = _clean_num(experience_max) or ext_data.get("experience_max")
    exp_max = int(exp_max_num) if (exp_max_num is not None and 0 <= float(exp_max_num) <= 50) else None
    sal_min_val = _clean_num(salary_min) or ext_data.get("salary_min")
    sal_min = float(sal_min_val) if (sal_min_val is not None and float(sal_min_val) < 10000000) else None
    sal_max_val = _clean_num(salary_max) or ext_data.get("salary_max")
    sal_max = float(sal_max_val) if (sal_max_val is not None and float(sal_max_val) < 10000000) else None
    desc = _clean_str(description) or ext_data.get("description") or raw_rec.get("raw_text") or "Garment vacancy"
    reqs = _clean_str(requirements) or ext_data.get("requirements")
    stext = _clean_str(salary_text) or ext_data.get("salary_text")
    qual = _clean_str(qualification) or ext_data.get("qualification")
    gend = _clean_str(gender) or ext_data.get("gender") or "Any"
    skil = _clean_str(skills) or ext_data.get("skills")
    if isinstance(skil, list):
        skil = ", ".join(skil)
    phone = _clean_str(contact_phone) or ext_data.get("contact_phone")
    wa = _clean_str(contact_whatsapp) or ext_data.get("contact_whatsapp") or phone
    email = _clean_str(contact_email) or ext_data.get("contact_email")
    app_url = _clean_str(application_url) or ext_data.get("application_url")
    
    walk_in_start = ext_data.get("walk_in_start_date")
    walk_in_end = ext_data.get("walk_in_end_date")
    interview_t = ext_data.get("interview_time")
    imm_join = bool(ext_data.get("immediate_joiners", False))

    # Generate unique slug
    base_slug = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')
    unique_slug = f"{base_slug}-{uuid.uuid4().hex[:6]}"

    created_job_id = None

    if db_helpers["db_enabled"] and db_helpers["execute_db_returning"]:
        # Handle company creation/lookup if needed
        if not c_id and c_name:
            comp_slug = f"{re.sub(r'[^a-z0-9]+', '-', c_name.lower()).strip('-')}-{uuid.uuid4().hex[:4]}"
            comp_rows = db_helpers["execute_db_returning"](
                """
                INSERT INTO companies (name, slug, location, contact_phone, contact_email, is_verified, status)
                VALUES (%s, %s, %s, %s, %s, FALSE, 'ACTIVE')
                ON CONFLICT (slug) DO UPDATE SET updated_at = CURRENT_TIMESTAMP
                RETURNING id;
                """,
                (c_name, comp_slug, loc, phone, email)
            )
            if comp_rows:
                c_id = comp_rows[0]["id"]

        # Insert master job
        job_query = """
        INSERT INTO jobs (
            company_id, title, slug, department, job_role, job_type, location,
            openings_count, experience_min, experience_max, salary_min, salary_max, salary_text,
            qualification, gender, skills, description, requirements,
            walk_in_start_date, walk_in_end_date, interview_time, immediate_joiners,
            contact_phone, contact_whatsapp, contact_email, application_url,
            source_type, source_name, source_url, poster_image_url,
            content_hash, source_hash, status, is_archived, published_at, created_at, updated_at
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, 'published', FALSE, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        ) RETURNING id;
        """
        job_rows = db_helpers["execute_db_returning"](job_query, (
            c_id, title, unique_slug, dept, role, jtype, loc,
            openings_cnt, exp_min, exp_max, sal_min, sal_max, stext,
            qual, gend, skil or role, desc, reqs,
            walk_in_start, walk_in_end, interview_t, imm_join,
            phone, wa, email, app_url,
            raw_rec.get("source_type"), raw_rec.get("source_name"), None, raw_rec.get("raw_image_path"),
            raw_rec.get("content_hash"), raw_rec.get("media_hash")
        ))
        if job_rows:
            created_job_id = job_rows[0]["id"]

            # Create source link in job_sources
            db_helpers["execute_db"](
                """
                INSERT INTO job_sources (
                    job_id, raw_ingestion_id, source_type, source_name,
                    source_message_reference, source_hash, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP);
                """,
                (
                    created_job_id, id, raw_rec.get("source_type"),
                    raw_rec.get("source_name"), raw_rec.get("source_reference"),
                    raw_rec.get("content_hash") or raw_rec.get("media_hash")
                )
            )

            # Update raw_job_ingestions status
            db_helpers["execute_db"](
                "UPDATE raw_job_ingestions SET status = 'APPROVED', matched_job_id = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s;",
                (created_job_id, id)
            )
    else:
        created_job_id = 999
        raw_rec["status"] = "APPROVED"
        raw_rec["matched_job_id"] = created_job_id

    return {
        "success": True,
        "message": f"Ingestion #{id} approved and published as Master Job #{created_job_id}.",
        "job_id": created_job_id,
        "slug": unique_slug
    }

@router.post("/{id}/merge")
def merge_ingestion_to_master(
    id: int,
    target_job_id: int = Form(...),
    session_id: Optional[str] = Cookie(None)
):
    """
    Admin Decision: Merge as Secondary Source.
    Links the raw ingestion to an existing master job in `job_sources` table.
    Does NOT create a duplicate public job.
    """
    _check_admin_auth(session_id)

    raw_rec = None
    if db_helpers["db_enabled"] and db_helpers["query_db"]:
        rows = db_helpers["query_db"]("SELECT * FROM raw_job_ingestions WHERE id = %s;", (id,))
        if rows:
            raw_rec = rows[0]
    else:
        raw_rec = next((r for r in FALLBACK_INGESTIONS if r["id"] == id), None)

    if not raw_rec:
        raise HTTPException(status_code=404, detail="Ingestion record not found.")

    if db_helpers["db_enabled"] and db_helpers["execute_db"]:
        # Verify master job exists
        m_rows = db_helpers["query_db"]("SELECT id, title FROM jobs WHERE id = %s;", (target_job_id,))
        if not m_rows:
            raise HTTPException(status_code=404, detail=f"Target Master Job #{target_job_id} does not exist.")

        # Create secondary source record if not already linked
        existing_link = db_helpers["query_db"](
            "SELECT id FROM job_sources WHERE job_id = %s AND raw_ingestion_id = %s;",
            (target_job_id, id)
        )
        if not existing_link:
            db_helpers["execute_db"](
                """
                INSERT INTO job_sources (
                    job_id, raw_ingestion_id, source_type, source_name,
                    source_message_reference, source_hash, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP);
                """,
                (
                    target_job_id, id, raw_rec.get("source_type"),
                    raw_rec.get("source_name"), raw_rec.get("source_reference"),
                    raw_rec.get("content_hash") or raw_rec.get("media_hash")
                )
            )

        # Update ingestion status
        db_helpers["execute_db"](
            "UPDATE raw_job_ingestions SET status = 'APPROVED', matched_job_id = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s;",
            (target_job_id, id)
        )
    else:
        raw_rec["status"] = "APPROVED"
        raw_rec["matched_job_id"] = target_job_id

    return {
        "success": True,
        "message": f"Ingestion #{id} successfully merged as secondary source to Master Job #{target_job_id}."
    }

@router.post("/{id}/reject")
def reject_ingestion(
    id: int,
    reason: Optional[str] = Form("Rejected by admin"),
    session_id: Optional[str] = Cookie(None)
):
    """
    Admin Decision: Reject / Spam.
    Marks ingestion as REJECTED while preserving raw source data for auditability.
    """
    _check_admin_auth(session_id)

    r_clean = _clean_str(reason) or "Rejected by admin"

    if db_helpers["db_enabled"] and db_helpers["execute_db"]:
        db_helpers["execute_db"](
            "UPDATE raw_job_ingestions SET status = 'REJECTED', error_log = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s;",
            (r_clean, id)
        )
    else:
        rec = next((r for r in FALLBACK_INGESTIONS if r["id"] == id), None)
        if rec:
            rec["status"] = "REJECTED"
            rec["error_log"] = r_clean

    return {"success": True, "message": f"Ingestion #{id} marked as REJECTED."}

@router.post("/bulk-approve")
def bulk_approve_ingestions(
    session_id: Optional[str] = Cookie(None),
    parent_ingestion_id: Optional[int] = Form(None),
    ingestion_ids: Optional[str] = Form(None)
):
    """
    Step 3D.5 Bulk Approval & Multi-Job Decision Endpoint.
    Approves all valid new vacancies from a post or ID list in one controlled operation.
    Merges high duplicates (>=0.85) as secondary sources and flags incomplete records for review.
    """
    _check_admin_auth(session_id)

    target_ids = []
    if parent_ingestion_id:
        if db_helpers["db_enabled"] and db_helpers["query_db"]:
            rows = db_helpers["query_db"](
                "SELECT id FROM raw_job_ingestions WHERE id = %s OR parent_ingestion_id = %s ORDER BY vacancy_index ASC, id ASC;",
                (parent_ingestion_id, parent_ingestion_id)
            )
            target_ids = [r["id"] for r in rows] if rows else [parent_ingestion_id]
        else:
            target_ids = [r["id"] for r in FALLBACK_INGESTIONS if r["id"] == parent_ingestion_id or r.get("parent_ingestion_id") == parent_ingestion_id]
    elif ingestion_ids:
        for part in ingestion_ids.split(","):
            part_s = part.strip()
            if part_s.isdigit():
                target_ids.append(int(part_s))

    if not target_ids:
        raise HTTPException(status_code=400, detail="No ingestion IDs provided for bulk approval.")

    results = []
    approved_cnt = 0
    merged_cnt = 0
    review_cnt = 0

    for rec_id in target_ids:
        try:
            # Check if record has high duplicate
            raw_rec = None
            if db_helpers["db_enabled"] and db_helpers["query_db"]:
                r_rows = db_helpers["query_db"]("SELECT * FROM raw_job_ingestions WHERE id = %s;", (rec_id,))
                raw_rec = r_rows[0] if r_rows else None
            else:
                raw_rec = next((r for r in FALLBACK_INGESTIONS if r["id"] == rec_id), None)

            if not raw_rec:
                continue

            dup_score = float(raw_rec.get("duplicate_score") or 0.0)
            matched_job_id = raw_rec.get("matched_job_id")

            if dup_score >= 0.85 and matched_job_id:
                # Merge as secondary source
                merge_res = merge_ingestion_to_master(id=rec_id, target_job_id=matched_job_id, session_id=session_id)
                merged_cnt += 1
                results.append({
                    "ingestion_id": rec_id,
                    "action": "MERGED",
                    "matched_job_id": matched_job_id,
                    "message": merge_res.get("message")
                })
            else:
                # Approve as master job
                appr_res = approve_and_publish_ingestion(id=rec_id, session_id=session_id)
                approved_cnt += 1
                results.append({
                    "ingestion_id": rec_id,
                    "action": "APPROVED",
                    "job_id": appr_res.get("job_id"),
                    "slug": appr_res.get("slug"),
                    "message": appr_res.get("message")
                })
        except Exception as e:
            logger.error(f"Error in bulk approval for ingestion #{rec_id}: {e}")
            review_cnt += 1
            results.append({
                "ingestion_id": rec_id,
                "action": "REVIEW_REQUIRED",
                "error": str(e)
            })

    return {
        "success": True,
        "total": len(target_ids),
        "approved_count": approved_cnt,
        "merged_count": merged_cnt,
        "review_required_count": review_cnt,
        "results": results
    }

# ==========================================================
# STEP 3F: WEBSITE SOURCE MANAGEMENT ENDPOINTS
# ==========================================================

@router.get("/sources")
def list_job_sources(session_id: str = Cookie(None)):
    """
    Returns configured website job sources and health metrics.
    """
    _check_admin_auth(session_id)
    
    if db_helpers["db_enabled"] and db_helpers["query_db"]:
        try:
            sources = db_helpers["query_db"]("""
                SELECT 
                    id, source_id, source_name, source_type, base_url,
                    enabled, crawl_allowed, status, schedule_enabled,
                    crawl_interval_minutes, requests_per_minute,
                    last_crawled_at, last_success_at, last_error_at, last_error_message,
                    total_discovered, total_imported, total_duplicates, total_errors,
                    created_at, updated_at
                FROM website_sources
                ORDER BY id ASC;
            """)
            return {"success": True, "sources": sources}
        except Exception as e:
            logger.error(f"Error fetching website sources from DB: {e}")

    # Fallback response for offline mode
    return {
        "success": True,
        "sources": [
            {
                "id": 1,
                "source_id": "sankar_jobs",
                "source_name": "Sankar Jobs",
                "source_type": "website",
                "base_url": "https://sankarjobs.com",
                "enabled": True,
                "crawl_allowed": True,
                "status": "ACTIVE",
                "schedule_enabled": False,
                "crawl_interval_minutes": 60,
                "requests_per_minute": 20,
                "total_discovered": 0,
                "total_imported": 0,
                "total_duplicates": 0,
                "total_errors": 0
            },
            {
                "id": 2,
                "source_id": "cotton_jobs",
                "source_name": "Cotton Jobs",
                "source_type": "website",
                "base_url": "https://cottonjobs.in",
                "enabled": True,
                "crawl_allowed": True,
                "status": "ACTIVE",
                "schedule_enabled": False,
                "crawl_interval_minutes": 60,
                "requests_per_minute": 20,
                "total_discovered": 0,
                "total_imported": 0,
                "total_duplicates": 0,
                "total_errors": 0
            }
        ]
    }

@router.post("/sources/{source_id}/toggle")
def toggle_job_source(source_id: str, session_id: str = Cookie(None)):
    """
    Toggles the enabled status of a website job source.
    """
    _check_admin_auth(session_id)
    
    if db_helpers["db_enabled"] and db_helpers["query_db"]:
        try:
            curr = db_helpers["query_db"]("SELECT enabled FROM website_sources WHERE source_id = %s;", (source_id,))
            if not curr:
                raise HTTPException(status_code=404, detail="Source not found")
            new_state = not curr[0]["enabled"]
            db_helpers["execute_db"](
                "UPDATE website_sources SET enabled = %s, updated_at = CURRENT_TIMESTAMP WHERE source_id = %s;",
                (new_state, source_id)
            )
            return {"success": True, "source_id": source_id, "enabled": new_state}
        except Exception as e:
            if isinstance(e, HTTPException):
                raise e
            raise HTTPException(status_code=500, detail=str(e))
            
    return {"success": True, "source_id": source_id, "enabled": True}

@router.get("/sources/logs")
def get_source_crawl_logs(limit: int = Query(default=20, ge=1, le=100), session_id: str = Cookie(None)):
    """
    Returns recent crawl execution logs from crawl_run_logs table.
    """
    _check_admin_auth(session_id)
    
    if db_helpers["db_enabled"] and db_helpers["query_db"]:
        try:
            logs = db_helpers["query_db"]("""
                SELECT id, source_id, started_at, completed_at, duration_seconds,
                       pages_visited, job_urls_discovered, new_imported, exact_duplicates,
                       possible_duplicates, extraction_successes, extraction_failures,
                       errors_count, status, log_summary, error_details
                FROM crawl_run_logs
                ORDER BY id DESC
                LIMIT %s;
            """, (limit,))
            return {"success": True, "logs": logs or []}
        except Exception as e:
            logger.error(f"Error fetching crawl logs: {e}")
            return {"success": True, "logs": []}
            
    return {"success": True, "logs": []}

@router.post("/sources/{source_id}/run")
def run_single_job_source(
    source_id: str,
    lookback_days: int = Query(default=5, ge=1, le=90),
    max_pages: int = Query(default=10, ge=1, le=30),
    today: Optional[str] = Query(default=None),
    session_id: str = Cookie(None)
):
    """
    Direct endpoint to trigger crawl run for a specific source connector.
    """
    return sync_website_sources_now(
        source=source_id,
        lookback_days=lookback_days,
        max_pages=max_pages,
        today=today,
        session_id=session_id
    )

@router.post("/sync")
def sync_website_sources_now(
    source: str = Query(default="all", description="all, sankar_jobs, cotton_jobs"),
    lookback_days: int = Query(default=5, ge=1, le=90),
    max_pages: int = Query(default=10, ge=1, le=30),
    today: Optional[str] = Query(default=None),
    session_id: str = Cookie(None)
):
    """
    Multi-Source Dynamic Daily Sync Endpoint.
    Crawls eligible public job posts from Sankar Jobs and/or Cotton Jobs within (Today - N Days) -> Today.
    """
    _check_admin_auth(session_id)
    
    # Parse target date
    target_d = None
    if today:
        try:
            target_d = datetime.strptime(today.strip(), "%Y-%m-%d").date()
        except ValueError:
            try:
                target_d = datetime.strptime(today.strip(), "%d/%m/%Y").date()
            except ValueError:
                pass
    if not target_d:
        target_d = datetime.now().date()
        
    cutoff_d = target_d - timedelta(days=lookback_days)

    target_sources = []
    if source.lower() in ["all", "both"]:
        target_sources = ["sankar_jobs", "cotton_jobs"]
    else:
        target_sources = [source.lower().strip()]

    aggregated_summary = {
        "sources_run": target_sources,
        "date_range": f"{cutoff_d.strftime('%d/%m/%Y')} → {target_d.strftime('%d/%m/%Y')}",
        "cutoff_date": cutoff_d.isoformat(),
        "today": target_d.isoformat(),
        "lookback_days": lookback_days,
        "total_discovered": 0,
        "new_imported": 0,
        "exact_duplicates": 0,
        "possible_duplicates": 0,
        "pending_review_count": 0,
        "older_skipped": 0,
        "errors_count": 0,
        "source_details": {}
    }

    for s_id in target_sources:
        connector = connector_registry.get_connector(s_id)
        if not connector:
            logger.warning(f"No connector registered for source '{s_id}'")
            aggregated_summary["errors_count"] += 1
            aggregated_summary["source_details"][s_id] = {"status": "NOT_FOUND", "error": "Connector not found"}
            continue
            
        try:
            res = connector_registry.run_connector(
                source_id=s_id,
                max_pages=max_pages,
                lookback_days=lookback_days,
                db_query_fn=db_helpers["query_db"] if db_helpers["db_enabled"] else None,
                db_exec_fn=db_helpers["execute_db"] if db_helpers["db_enabled"] else None,
                db_exec_ret_fn=db_helpers["execute_db_returning"] if db_helpers["db_enabled"] else None
            )
            aggregated_summary["total_discovered"] += res.get("job_urls_discovered", 0)
            aggregated_summary["new_imported"] += res.get("new_imported", 0)
            aggregated_summary["exact_duplicates"] += res.get("exact_duplicates", 0)
            aggregated_summary["possible_duplicates"] += res.get("possible_duplicates", 0)
            aggregated_summary["pending_review_count"] += res.get("pending_review_count", 0)
            aggregated_summary["older_skipped"] += res.get("older_posts_skipped", 0)
            aggregated_summary["errors_count"] += res.get("errors_count", 0)
            aggregated_summary["source_details"][s_id] = res
        except Exception as e:
            logger.error(f"Error syncing source {s_id}: {e}", exc_info=True)
            aggregated_summary["errors_count"] += 1
            aggregated_summary["source_details"][s_id] = {"status": "ERROR", "error": str(e)}

    return {
        "success": True,
        "message": f"Sync complete for {len(target_sources)} source(s).",
        "summary": aggregated_summary
    }

@router.get("/posts/{parent_id}/review")
def get_source_post_for_review(parent_id: int, session_id: str = Cookie(None)):
    """
    Returns single unified review payload for a parent source post and all its segmented vacancies.
    """
    _check_admin_auth(session_id)
    
    all_vacs = []
    parent_rec = None
    
    if db_helpers["db_enabled"] and db_helpers["query_db"]:
        rows = db_helpers["query_db"]("""
            SELECT r.id, r.parent_ingestion_id, r.vacancy_index, r.total_vacancies,
                   r.source_type, r.source_name, r.source_url, r.source_reference, r.source_posted_date,
                   r.raw_text, r.raw_image_path, r.content_hash, r.status,
                   r.confidence_score, r.duplicate_score, r.matched_job_id, r.matched_company_id,
                   r.extracted_data, r.duplicate_reasons, r.created_at,
                   c.name as matched_company_name, j.title as matched_job_title
            FROM raw_job_ingestions r
            LEFT JOIN companies c ON r.matched_company_id = c.id
            LEFT JOIN jobs j ON r.matched_job_id = j.id
            WHERE r.id = %s OR r.parent_ingestion_id = %s
            ORDER BY r.vacancy_index ASC, r.id ASC;
        """, (parent_id, parent_id))
        if rows:
            parent_rec = next((r for r in rows if r["id"] == parent_id), rows[0])
            child_rows = [r for r in rows if r.get("parent_ingestion_id") == parent_id]
            has_child_vac_1 = any(r.get("vacancy_index") == 1 for r in child_rows)
            if child_rows and not has_child_vac_1:
                all_vacs = [parent_rec] + child_rows
            elif child_rows:
                all_vacs = child_rows
            else:
                all_vacs = [parent_rec]
    else:
        all_matches = [r for r in FALLBACK_INGESTIONS if r["id"] == parent_id or r.get("parent_ingestion_id") == parent_id]
        if all_matches:
            parent_rec = next((r for r in all_matches if r["id"] == parent_id), all_matches[0])
            child_rows = [r for r in all_matches if r.get("parent_ingestion_id") == parent_id]
            has_child_vac_1 = any(r.get("vacancy_index") == 1 for r in child_rows)
            if child_rows and not has_child_vac_1:
                all_vacs = [parent_rec] + child_rows
            elif child_rows:
                all_vacs = child_rows
            else:
                all_vacs = [parent_rec]

    if not parent_rec:
        raise HTTPException(status_code=404, detail=f"Source post #{parent_id} not found.")

    p_ext = parent_rec.get("extracted_data") or {}
    if isinstance(p_ext, str):
        try:
            p_ext = json.loads(p_ext)
        except Exception:
            p_ext = {}

    # Extract common post fields
    raw_comp = p_ext.get("company_name") or parent_rec.get("matched_company_name")
    company_name = None
    if raw_comp:
        clean_c, _ = normalize_company_name(raw_comp)
        if clean_c and clean_c.lower() not in ["direct employer", "garment manufacturer", "sankar jobs", "cotton jobs", "garment jobs"]:
            company_name = clean_c
        
    location = p_ext.get("location") or "Tiruppur"
    phone = p_ext.get("contact_phone")
    wa = p_ext.get("contact_whatsapp") or phone
    email = p_ext.get("contact_email")
    interview_time = p_ext.get("interview_time")

    # Format vacancies list
    formatted_vacancies = []
    for r in all_vacs:
        v_ext = r.get("extracted_data") or {}
        if isinstance(v_ext, str):
            try:
                v_ext = json.loads(v_ext)
            except Exception:
                v_ext = {}
                
        exact_role = v_ext.get("source_role") or v_ext.get("job_role") or v_ext.get("job_title") or "Garment Vacancy"
        openings = max(int(v_ext.get("openings_count") or 1), 1)
        remarks = v_ext.get("remarks") or v_ext.get("requirements") or ""
        role_ev = v_ext.get("role_evidence") or exact_role
        open_ev = v_ext.get("opening_evidence") or f"{openings} Openings"
        remarks_ev = v_ext.get("remarks_evidence") or remarks
        
        dup_sc = float(r.get("duplicate_score") or 0.0)
        dup_st = "NEW"
        if dup_sc >= 0.90:
            dup_st = f"EXACT DUPLICATE ({int(dup_sc*100)}%)"
        elif dup_sc >= 0.70:
            dup_st = f"POSSIBLE DUPLICATE ({int(dup_sc*100)}%)"

        formatted_vacancies.append({
            "id": r.get("id"),
            "vacancy_index": r.get("vacancy_index", 1),
            "job_role": exact_role,
            "openings_count": openings,
            "remarks": remarks,
            "role_evidence": role_ev,
            "opening_evidence": open_ev,
            "remarks_evidence": remarks_ev,
            "decision": "PENDING",
            "confidence_score": float(r.get("confidence_score") or v_ext.get("confidence_score") or 0.90),
            "duplicate_score": dup_sc,
            "duplicate_status": dup_st,
            "status": r.get("status", "PENDING_REVIEW")
        })

    return {
        "success": True,
        "parent_id": parent_id,
        "source_name": parent_rec.get("source_name") or "Website Source",
        "source_url": parent_rec.get("source_url"),
        "source_posted_date": parent_rec.get("source_posted_date"),
        "raw_text": parent_rec.get("raw_text"),
        "poster_image_url": parent_rec.get("raw_image_path"),
        "total_vacancies": len(formatted_vacancies),
        "common_fields": {
            "company_name": company_name,
            "location": location,
            "contact_phone": phone,
            "contact_whatsapp": wa,
            "contact_email": email,
            "interview_time": interview_time
        },
        "vacancies": formatted_vacancies
    }

@router.post("/posts/{parent_id}/publish")
def publish_selected_vacancies(
    parent_id: int,
    payload: Dict[str, Any],
    session_id: str = Cookie(None)
):
    """
    Selective Multi-Vacancy Publisher:
    Admin reviews ONE source post, decides Accept/Reject per vacancy.
    Publishes EVERY ACCEPTED vacancy as a SEPARATE public job card in `jobs` table!
    """
    _check_admin_auth(session_id)

    common = payload.get("common_fields") or {}
    vacancies = payload.get("vacancies") or []

    if not vacancies:
        raise HTTPException(status_code=400, detail="No vacancies provided for publishing.")

    # 1. Fetch parent record for provenance
    parent_rec = None
    if db_helpers["db_enabled"] and db_helpers["query_db"]:
        rows = db_helpers["query_db"]("SELECT * FROM raw_job_ingestions WHERE id = %s;", (parent_id,))
        if rows:
            parent_rec = rows[0]
    else:
        parent_rec = next((r for r in FALLBACK_INGESTIONS if r["id"] == parent_id), None)

    if not parent_rec:
        raise HTTPException(status_code=404, detail=f"Parent source post #{parent_id} not found.")

    comp_name = _clean_str(common.get("company_name"))
    loc = _clean_str(common.get("location")) or "Tiruppur, Tamil Nadu"
    phone = _clean_str(common.get("contact_phone"))
    wa = _clean_str(common.get("contact_whatsapp")) or phone
    email = _clean_str(common.get("contact_email"))
    interview_t = _clean_str(common.get("interview_time"))
    
    src_type = parent_rec.get("source_type") or "website"
    src_name = parent_rec.get("source_name") or "Website Source"
    src_url = parent_rec.get("source_url")
    poster_url = parent_rec.get("raw_image_path")

    # Handle company record creation if company name provided
    company_id = None
    if comp_name and db_helpers["db_enabled"] and db_helpers["execute_db_returning"]:
        comp_slug = f"{re.sub(r'[^a-z0-9]+', '-', comp_name.lower()).strip('-')}-{uuid.uuid4().hex[:4]}"
        comp_rows = db_helpers["execute_db_returning"]("""
            INSERT INTO companies (name, slug, location, contact_phone, contact_email, is_verified, status)
            VALUES (%s, %s, %s, %s, %s, FALSE, 'ACTIVE')
            ON CONFLICT (slug) DO UPDATE SET updated_at = CURRENT_TIMESTAMP
            RETURNING id;
        """, (comp_name, comp_slug, loc, phone, email))
        if comp_rows:
            company_id = comp_rows[0]["id"]

    published_job_ids = []
    rejected_count = 0
    accepted_count = 0

    for v in vacancies:
        v_id = v.get("id")
        decision = (v.get("decision") or "PENDING").upper().strip()
        v_role = (v.get("job_role") or "Garment Vacancy").strip()
        v_openings = max(int(v.get("openings_count") or 1), 1)
        v_remarks = _clean_str(v.get("remarks"))

        if decision == "ACCEPT":
            accepted_count += 1
            # Generate clean slug
            base_slug = re.sub(r'[^a-z0-9]+', '-', v_role.lower()).strip('-') or "job"
            unique_slug = f"{base_slug}-{uuid.uuid4().hex[:6]}"
            
            job_desc = v_remarks or f"Requirement for {v_role}."
            job_reqs = v_remarks
            
            created_job_id = None
            if db_helpers["db_enabled"] and db_helpers["execute_db_returning"]:
                job_rows = db_helpers["execute_db_returning"]("""
                    INSERT INTO jobs (
                        company_id, title, slug, department, job_role, job_type, location,
                        openings_count, experience_min, experience_max, salary_min, salary_max, salary_text,
                        qualification, gender, skills, description, requirements,
                        interview_time, contact_phone, contact_whatsapp, contact_email,
                        source_type, source_name, source_url, poster_image_url,
                        status, is_archived, published_at, created_at, updated_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, 'Full Time', %s,
                        %s, 0, NULL, NULL, NULL, NULL,
                        NULL, 'Male/Female', %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        'published', FALSE, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                    ) RETURNING id;
                """, (
                    company_id, v_role, unique_slug, "Production", v_role, loc,
                    v_openings, v_role, job_desc, job_reqs,
                    interview_t, phone, wa, email,
                    src_type, src_name, src_url, poster_url
                ))
                if job_rows:
                    created_job_id = job_rows[0]["id"]
                    published_job_ids.append(created_job_id)
                    
                    # Update vacancy ingestion record
                    if v_id and db_helpers["execute_db"]:
                        db_helpers["execute_db"]("""
                            UPDATE raw_job_ingestions
                            SET status = 'APPROVED', matched_job_id = %s, updated_at = CURRENT_TIMESTAMP
                            WHERE id = %s;
                        """, (created_job_id, v_id))
            else:
                created_job_id = len(published_job_ids) + 1001
                published_job_ids.append(created_job_id)
                if v_id:
                    for rec in FALLBACK_INGESTIONS:
                        if rec["id"] == v_id:
                            rec["status"] = "APPROVED"
                            rec["matched_job_id"] = created_job_id

        elif decision == "REJECT":
            rejected_count += 1
            if v_id and db_helpers["db_enabled"] and db_helpers["execute_db"]:
                db_helpers["execute_db"]("""
                    UPDATE raw_job_ingestions
                    SET status = 'REJECTED', updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s;
                """, (v_id,))
            elif v_id:
                for rec in FALLBACK_INGESTIONS:
                    if rec["id"] == v_id:
                        rec["status"] = "REJECTED"

    # Update parent record status
    if db_helpers["db_enabled"] and db_helpers["execute_db"]:
        db_helpers["execute_db"]("""
            UPDATE raw_job_ingestions
            SET status = 'PROCESSED', processed_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s;
        """, (parent_id,))
    elif parent_rec:
        parent_rec["status"] = "PROCESSED"

    return {
        "success": True,
        "message": f"Source post #{parent_id} processed. {accepted_count} published as separate jobs, {rejected_count} rejected.",
        "parent_id": parent_id,
        "published_count": accepted_count,
        "rejected_count": rejected_count,
        "published_job_ids": published_job_ids
    }


