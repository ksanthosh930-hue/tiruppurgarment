"""
AI Provider Abstraction Layer for Multi-Modal Job Poster & Text Extraction.
Supports Google Gemini Vision, Windows Native OCR, and a built-in deterministic offline Rule-Based Engine.
"""

import os
import re
import json
import base64
import logging
import urllib.request
import urllib.error
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, Tuple, List
from services.normalizer import (
    normalize_company_name, normalize_department, normalize_job_role,
    normalize_location, normalize_phone_number, parse_salary_range, parse_experience_range,
    parse_openings_count, parse_walk_in_details, parse_gender_requirement,
    parse_role_skills_and_requirements, extract_all_phone_numbers
)
from services.ocr_engine import extract_text_from_image_bytes

logger = logging.getLogger("DigiGarment.AIProvider")

EXTRACTION_SYSTEM_PROMPT = """
You are DigiGarment's Expert Garment Job Ingestion AI for the Tiruppur Export Cluster.
Your task is to extract structured multi-vacancy job data from the provided job flyer poster image and/or text caption.

CRITICAL MULTI-VACANCY EXTRACTION RULES:
1. Detect ALL distinct vacancy roles present in the flyer or text. Do NOT collapse multiple roles into one.
2. For each vacancy, extract:
   - job_title & job_role (e.g. 'Merchandising Manager', 'Senior Merchandiser', 'Accounts Executive', 'Checking Supervisor', 'Line QC', 'Line Supervisor')
   - openings_count (integer >= 1, e.g. 1 for '1 No.', 2 for '2 Nos.', 5 for '5 Nos.')
   - department (Merchandising, Accounts, Quality, Sewing, Production, Cutting, Finishing, HR, Maintenance, Stores, etc.)
   - experience_min and experience_max (integers, e.g. 4 and 5 for '4-5 Years')
   - gender ('Male', 'Female', 'Male/Female', or 'Any')
   - skills (role-specific skills, e.g. ['Tally Prime', 'GST', 'TDS'] strictly for Accounts Executive)
   - requirements (role-specific verbatim requirement text)
3. Extract shared post-level metadata:
   - company_name (e.g. 'Navagiri Apparel')
   - location (e.g. 'Kangayam Road, Vijayapuram, Tiruppur')
   - contact phones (clean 10-digit Indian numbers)
   - walk-in interview dates, interview timings, immediate joiners preference
4. Return strict, valid JSON matching the exact schema below.

JSON Output Schema:
{
  "company_name": "string or null",
  "location": "string",
  "contact_phone": "string or null",
  "contact_whatsapp": "string or null",
  "contact_email": "string or null",
  "website_source": "string or null",
  "walk_in_start_date": "YYYY-MM-DD or null",
  "walk_in_end_date": "YYYY-MM-DD or null",
  "walk_in_date_text": "string or null",
  "interview_time": "string or null",
  "immediate_joiners": boolean,
  "total_vacancies": integer,
  "total_openings": integer,
  "vacancies": [
    {
      "vacancy_index": integer,
      "job_title": "string",
      "department": "string",
      "job_role": "string",
      "openings_count": integer,
      "job_type": "string (Full Time, Part Time, Contract)",
      "location": "string",
      "experience_min": integer or null,
      "experience_max": integer or null,
      "salary_min": number or null,
      "salary_max": number or null,
      "salary_text": "string or null",
      "qualification": "string or null",
      "gender": "string (Any, Male, Female, Male/Female)",
      "skills": ["string"],
      "description": "string",
      "requirements": "string or null",
      "confidence_score": number between 0.0 and 1.0
    }
  ]
}
"""

class AIProvider(ABC):
    @abstractmethod
    def extract_job(
        self,
        text: Optional[str] = None,
        image_bytes: Optional[bytes] = None,
        image_mime: Optional[str] = None
    ) -> Tuple[Dict[str, Any], Dict[str, Any], float, List[str]]:
        """
        Extracts structured single job data from text and/or image.
        Returns: (extracted_data_dict, raw_ai_response_dict, confidence_score, warnings_list)
        """
        pass

    @abstractmethod
    def extract_multi_jobs(
        self,
        text: Optional[str] = None,
        image_bytes: Optional[bytes] = None,
        image_mime: Optional[str] = None
    ) -> Tuple[Dict[str, Any], Dict[str, Any], float, List[str]]:
        """
        Extracts structured multi-job vacancies from text and/or image in a single operation.
        Returns: (multi_job_dict, raw_ai_response_dict, confidence_score, warnings_list)
        """
        pass

class RuleBasedFallbackProvider(AIProvider):
    """
    High-accuracy deterministic extractor for offline mode, local OCR,
    and fast parsing of garment job flyers & WhatsApp forwards.
    """
    def extract_job(
        self,
        text: Optional[str] = None,
        image_bytes: Optional[bytes] = None,
        image_mime: Optional[str] = None
    ) -> Tuple[Dict[str, Any], Dict[str, Any], float, List[str]]:
        multi_res, raw_resp, conf, warns = self.extract_multi_jobs(text, image_bytes, image_mime)
        vacancies = multi_res.get("vacancies", [])
        primary = vacancies[0] if vacancies else {}
        return (primary, raw_resp, conf, warns)

    def extract_multi_jobs(
        self,
        text: Optional[str] = None,
        image_bytes: Optional[bytes] = None,
        image_mime: Optional[str] = None
    ) -> Tuple[Dict[str, Any], Dict[str, Any], float, List[str]]:
        warnings = []
        missing = []
        
        # 1. Multi-Modal Vision / OCR Fusion
        ocr_text = ""
        if image_bytes:
            suffix = ".png" if image_mime == "image/png" else ".jpeg"
            ocr_text = extract_text_from_image_bytes(image_bytes, suffix=suffix)
            
        combined_text = ""
        if text and text.strip() and ocr_text:
            combined_text = f"{text.strip()}\n\n[POSTER OCR]\n{ocr_text}"
        elif ocr_text:
            combined_text = ocr_text
        else:
            combined_text = (text or "").strip()

        # 2. Extract Shared Phone Numbers
        all_phones = extract_all_phone_numbers(combined_text)
        primary_phone = all_phones[0] if all_phones else None
        secondary_phone = all_phones[1] if len(all_phones) > 1 else primary_phone
        if not primary_phone:
            missing.append("contact_phone")
            warnings.append("No valid 10-digit contact phone number detected in source.")
            
        # 3. Extract Shared Email & Website Source
        email_match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', combined_text)
        email = email_match.group(0).lower() if email_match else None
        
        web_match = re.search(r'\b(?:www\.[a-z0-9\.-]+\.[a-z]{2,}|https?://[^\s]+)\b', combined_text, re.IGNORECASE)
        website_source = web_match.group(0) if web_match else None

        # 4. Extract Shared Walk-In & Interview Details
        walk_in_info = parse_walk_in_details(combined_text)

        # 5. Extract Shared Location
        location = normalize_location(combined_text)
        
        # 6. Extract Shared Company Name
        company_name = None
        
        # Explicit 'COMPANY: <Name>' or 'COMPANY <Name>' detection
        comp_tag_match = re.search(r'\bCOMPANY\s*[:=-]?\s*([A-Za-z0-9\s&.,\'"-]+)', combined_text, re.IGNORECASE)
        if comp_tag_match:
            cand_comp = comp_tag_match.group(1).split("\n")[0].strip()
            # Clean trailing location phrases
            cand_comp = re.split(r'\b(?:kangayam|vijayapuram|tiruppur|tirupur|road|near|opp|behind)\b', cand_comp, flags=re.IGNORECASE)[0].strip()
            if cand_comp and len(cand_comp) >= 3:
                company_name, _ = normalize_company_name(cand_comp)

        # Hiring statement: e.g. 'WANTED Navagiri Apparel is hiring' or 'Navagiri Apparel is hiring'
        if not company_name:
            hire_match = re.search(r'\b(?:wanted\s+|hiring\s+)?([A-Za-z0-9\s&.,\'-]+?)\s+(?:is\s+hiring|urgently\s+requires|requires|needs)\b', combined_text, re.IGNORECASE)
            if hire_match:
                cand_comp = hire_match.group(1).strip()
                cand_comp = re.sub(r'^(?:wanted|urgent|hiring|aff\d+\w*)\s*', '', cand_comp, flags=re.IGNORECASE).strip()
                if cand_comp and len(cand_comp) >= 3 and not any(r in cand_comp.lower() for r in ["candidate", "position", "experienced"]):
                    company_name, _ = normalize_company_name(cand_comp)

        # Header lines scan
        if not company_name:
            lines = [l.strip() for l in combined_text.splitlines() if l.strip()]
            for line in lines[:5]:
                lower_l = line.lower()
                if any(lower_l.startswith(p) for p in ["experience", "exp:", "salary", "sal:", "qualification", "qual:", "wanted", "1.", "2.", "3.", "contact", "phone", "location"]):
                    continue
                if any(suffix in lower_l for suffix in ["garments", "apparels", "apparel", "exports", "textiles", "knits", "clothing", "mills", "pvt ltd", "private limited", "creations", "fashions", "knitters"]):
                    clean_l = re.sub(r'^(?:wanted|urgent requirement|hiring|open positions|aff\d+\w*|multiple\s+[a-z\s]+positions\s+at|openings\s+at|vacancies\s+at|jobs\s+at)\s*[:=-]?\s*', '', line, flags=re.IGNORECASE).strip()
                    clean_l = re.sub(r'^.*?\bat\s+', '', clean_l, flags=re.IGNORECASE).strip()
                    if clean_l and len(clean_l) >= 3:
                        company_name, _ = normalize_company_name(clean_l)
                        break

        # Suffix/Footer scan if company listed at bottom
        if not company_name:
            lines = [l.strip() for l in combined_text.splitlines() if l.strip()]
            for line in lines[-8:]:
                lower_l = line.lower()
                if any(lower_l.startswith(p) for p in ["experience", "exp:", "salary", "sal:", "qualification", "qual:", "wanted", "1.", "2.", "3.", "contact", "phone"]):
                    continue
                if any(suffix in lower_l for suffix in ["garments", "apparels", "apparel", "exports", "textiles", "knits", "clothing", "mills", "knitters"]):
                    clean_l = re.sub(r'^(?:company|unit|factory|address)\s*[:=-]?\s*', '', line, flags=re.IGNORECASE).strip()
                    clean_l = re.split(r'\b(?:kangayam|vijayapuram|tiruppur|tirupur|road)\b', clean_l, flags=re.IGNORECASE)[0].strip()
                    if clean_l and len(clean_l) >= 3:
                        company_name, _ = normalize_company_name(clean_l)
                        break

        if not company_name:
            company_name = None  # Safe: do NOT inject demo name

        # 7. Segment Multi-Job Vacancy Blocks
        role_indicator_keywords = [
            "merchandising manager", "senior merchandiser", "senior merchandisers", "junior merchandiser", "junior merchandisers",
            "merchandiser", "sampling merchandiser", "asst merchandiser", "costing executive",
            "accounts executive", "account executive", "accountant",
            "checking supervisor", "checking supervisors", "line qc", "inline qc", "line supervisor", "line supervisors",
            "production supervisor", "floor supervisor", "production manager", "production incharge", "production assistant",
            "quality inspector", "quality auditor", "quality supervisor", "quality manager", "qa manager", "qc checker", "quality controller",
            "cutting master", "cutting incharge", "cutting assistant", "pattern master", "cad master", "cad pattern master",
            "sample tailor", "tailor", "sewing operator", "sewing machine operator",
            "finishing supervisor", "finishing incharge", "packing supervisor", "packing incharge", "printing master", "embroidery operator",
            "ie executive", "industrial engineer", "ppc executive", "store keeper", "store incharge", "store assistant",
            "fabric assistant", "fabric incharge", "fabric manager", "fabric deo", "store deo", "it assistant", "hr executive", "hr manager",
            "training manager", "erp incharge", "erp operator", "driver", "mechanic"
        ]

        # Break text into logical blocks or lines
        # Segment long lines or text blocks containing multiple role titles or numbered items
        split_pat = re.compile(
            r'(?=\b(?:' + '|'.join(re.escape(k) for k in sorted(role_indicator_keywords, key=len, reverse=True)) + r')\b|\b(?:WALK-IN|COMPANY|OPEN POSITIONS)\b|\d+[\.\)\-]\s+)',
            re.IGNORECASE
        )
        
        total_lines_cnt = len([l for l in combined_text.splitlines() if l.strip()])
        raw_lines = []
        for line in combined_text.splitlines():
            l_str = line.strip()
            if not l_str or l_str == "[POSTER OCR]":
                continue
            if len(l_str) > 80 and total_lines_cnt <= 4:
                parts = [p.strip() for p in split_pat.split(l_str) if p.strip()]
                raw_lines.extend(parts)
            else:
                raw_lines.append(l_str)

        detected_blocks = []
        
        for idx, line in enumerate(raw_lines):
            lower_l = line.lower()
            
            # Skip if this line is purely a metadata line (experience, salary, location, contact, posted date)
            if any(lower_l.startswith(prefix) for prefix in [
                "experience:", "experience :", "exp:", "exp :",
                "salary:", "salary :", "sal:", "sal :",
                "qualification:", "qualification :", "qual:", "qual :",
                "location:", "location :", "loc:", "loc :",
                "contact:", "contact :", "phone:", "phone :", "mobile:",
                "posted on:", "posted:", "walk-in:", "walk-in ", "interview:",
                "note:", "requirements:", "skills:", "gender:", "company:",
                "position:", "position :"
            ]):
                continue

            # Check if this line contains a recognized vacancy role
            matched_kw = None
            for kw in role_indicator_keywords:
                # Match word boundary
                if re.search(r'\b' + re.escape(kw) + r'\b', lower_l):
                    matched_kw = kw
                    break
            
            # Tamil roles fallback
            if not matched_kw:
                if any(t in lower_l for t in ["மெர்ச்சண்டைசர்", "சூப்பர்வைசர்", "செக்கர்", "தையல்", "அயர்னிங்", "பேக்கிங்", "குவாலிட்டி"]):
                    matched_kw = "Garment Role"

            if matched_kw:
                # Gather contextual text for this vacancy (consume subsequent lines until next role/section)
                context_block = line
                for offset in range(1, 4):
                    if idx + offset < len(raw_lines):
                        nxt = raw_lines[idx + offset]
                        nxt_lower = nxt.lower()
                        is_next_role = any(re.search(r'\b' + re.escape(kw) + r'\b', nxt_lower) for kw in role_indicator_keywords)
                        is_next_section = any(nxt_lower.startswith(k) for k in ["walk-in", "interview", "contact", "phone", "location", "address", "company", "www.", "time:", "open positions"])
                        is_next_num = bool(re.match(r'^\d+[\.\)\-]\s+', nxt))
                        if not is_next_role and not is_next_section and not is_next_num:
                            context_block += " " + nxt
                        else:
                            break

                # 1. Parse Openings Count
                openings = parse_openings_count(context_block)
                
                # 2. Parse Experience
                emin, emax = parse_experience_range(context_block)
                if emin == 0 and len(raw_lines) <= 8:
                    g_emin, g_emax = parse_experience_range(combined_text)
                    if g_emin > 0:
                        emin, emax = g_emin, g_emax
                
                # 3. Parse Salary
                smin, smax, stext = parse_salary_range(context_block)
                if smin is None:
                    g_smin, g_smax, g_stext = parse_salary_range(combined_text)
                    if g_smin is not None:
                        smin, smax, stext = g_smin, g_smax, g_stext
                
                # 4. Parse Gender
                gender = parse_gender_requirement(context_block)
                
                # 5. Determine Canonical Role & Clean Title
                role_dept = normalize_department(None, text_context=context_block)
                _, canonical_role = normalize_job_role(matched_kw if matched_kw != "Garment Role" else context_block, dept=role_dept)
                
                # Extract clean verbatim source title from block (strip numbers, bullets, openings count suffix, or parenthetical remarks)
                clean_title_match = re.search(r'^(?:\d+[\.\)\-:]|\*|\-|•|✔|👉|\+)?\s*([A-Za-z\s/&]+?)(?:\s*[-–—:]\s*\d|\s*\(|\s*experience|\s*exp:|\s*salary|\s*walk|\s*wanted|$)', line, re.IGNORECASE)
                raw_extracted_title = clean_title_match.group(1).strip() if clean_title_match else ""
                
                # Title-case clean source title if all caps, preserving exact designation wording
                if raw_extracted_title:
                    clean_source_role = raw_extracted_title.title()
                else:
                    clean_source_role = canonical_role
                    
                if len(clean_source_role) < 3 or len(clean_source_role) > 80:
                    clean_source_role = canonical_role

                # 6. Parse Role-Specific Skills & Facts for Remarks
                skills, req_text = parse_role_skills_and_requirements(context_block, canonical_role)
                
                # Build fact-only remarks from context_block lines (excluding role title and contact/location headers)
                remark_facts = []
                for b_line in context_block.splitlines():
                    bl_s = b_line.strip()
                    bl_lower = bl_s.lower()
                    if not bl_s or bl_s == line.strip():
                        continue
                    if any(k in bl_lower for k in ["share on whatsapp", "call employer", "navigation menu", "copyright", "sankar jobs", "cotton jobs", "browse jobs"]):
                        continue
                    if re.match(r'^(?:contact|phone|mobile|location|address|company|interview time)\s*[:=-]', bl_lower):
                        continue
                    remark_facts.append(bl_s)
                    
                if not remark_facts:
                    # Fallback to isolated experience / salary / skills if detected in context
                    if emin > 0:
                        remark_facts.append(f"Experience: {emin}{f'-{emax}' if emax else '+'} Years")
                    if stext:
                        remark_facts.append(f"Salary: {stext}")
                    if req_text:
                        remark_facts.append(req_text)
                        
                vacancy_remarks = "\n".join(remark_facts).strip() if remark_facts else None

                detected_blocks.append({
                    "raw_text": context_block,
                    "source_role": clean_source_role,
                    "public_job_role": clean_source_role,
                    "job_title": clean_source_role,
                    "canonical_role": canonical_role,
                    "department": role_dept,
                    "openings_count": openings,
                    "experience_min": emin or 0,
                    "experience_max": emax,
                    "salary_min": smin,
                    "salary_max": smax,
                    "salary_text": stext,
                    "gender": gender,
                    "skills": skills,
                    "remarks": vacancy_remarks,
                    "role_evidence": line.strip(),
                    "opening_evidence": f"{openings} Openings (from '{context_block[:60].strip()}')",
                    "remarks_evidence": vacancy_remarks,
                    "requirements": vacancy_remarks
                })

        # Deduplicate within same post if duplicate role detected
        unique_vacancies = []
        seen_roles = {}
        for block in detected_blocks:
            key = (block["department"], block["canonical_role"].lower())
            if key not in seen_roles:
                seen_roles[key] = block
                unique_vacancies.append(block)
            else:
                existing = seen_roles[key]
                if block["openings_count"] > existing["openings_count"]:
                    existing["openings_count"] = block["openings_count"]

        # Single-Job Fallback if no multi-role blocks detected
        if not unique_vacancies:
            if combined_text:
                dept = normalize_department(None, text_context=combined_text)
                _, canonical_role = normalize_job_role(combined_text, dept=dept)
                emin, emax = parse_experience_range(combined_text)
                smin, smax, stext = parse_salary_range(combined_text)
                openings = parse_openings_count(combined_text)
                gender = parse_gender_requirement(combined_text)
                skills, req_text = parse_role_skills_and_requirements(combined_text, canonical_role)
                
                clean_title_match = re.search(r'^(?:\d+[\.\)\-:]|\*|\-|•|✔|👉|\+)?\s*([A-Za-z\s/&]+?)(?:\s*[-–—:]\s*\d|\s*\(|\s*experience|\s*exp:|\s*salary|\s*walk|\s*wanted|$)', combined_text, re.IGNORECASE)
                raw_extracted_title = clean_title_match.group(1).strip() if clean_title_match else ""
                clean_source_role = raw_extracted_title.title() if raw_extracted_title else canonical_role
                if len(clean_source_role) < 3 or len(clean_source_role) > 80:
                    clean_source_role = canonical_role

                fallback_remarks = req_text or (f"Experience: {emin} Years" if emin > 0 else None)

                unique_vacancies.append({
                    "raw_text": combined_text,
                    "source_role": clean_source_role,
                    "public_job_role": clean_source_role,
                    "job_title": clean_source_role,
                    "canonical_role": canonical_role,
                    "department": dept,
                    "openings_count": openings,
                    "experience_min": emin or 0,
                    "experience_max": emax,
                    "salary_min": smin,
                    "salary_max": smax,
                    "salary_text": stext,
                    "gender": gender,
                    "skills": skills,
                    "remarks": fallback_remarks,
                    "role_evidence": clean_source_role,
                    "opening_evidence": f"{openings} Openings",
                    "remarks_evidence": fallback_remarks,
                    "requirements": fallback_remarks
                })

        # 8. Build Standardized Multi-Job Output Array
        vacancies = []
        for idx, vac in enumerate(unique_vacancies, 1):
            # Dynamic confidence calculation per vacancy
            v_conf = 0.70
            if vac["source_role"]:
                v_conf += 0.08
            if vac["department"] and vac["department"] != "Other":
                v_conf += 0.05
            if company_name:
                v_conf += 0.05
            if primary_phone:
                v_conf += 0.05
            if vac.get("experience_min") or vac.get("experience_max"):
                v_conf += 0.03
            if vac.get("skills"):
                v_conf += 0.02
                
            vac_dict = {
                "vacancy_index": idx,
                "source_role": vac["source_role"],
                "public_job_role": vac["public_job_role"],
                "job_title": vac["source_role"],
                "department": vac["department"],
                "job_role": vac["source_role"],
                "canonical_role": vac["canonical_role"],
                "openings_count": vac["openings_count"],
                "job_type": "Full Time",
                "location": location,
                "experience_min": vac["experience_min"],
                "experience_max": vac["experience_max"],
                "salary_min": vac["salary_min"],
                "salary_max": vac["salary_max"],
                "salary_text": vac["salary_text"],
                "qualification": None,
                "gender": vac["gender"],
                "skills": vac["skills"],
                "remarks": vac["remarks"],
                "role_evidence": vac["role_evidence"],
                "opening_evidence": vac["opening_evidence"],
                "remarks_evidence": vac["remarks_evidence"],
                "description": vac["remarks"] or f"Requirement for {vac['source_role']}.",
                "requirements": vac["remarks"],
                "contact_phone": primary_phone,
                "contact_whatsapp": secondary_phone or primary_phone,
                "contact_email": email,
                "application_url": None,
                "confidence_score": round(max(min(v_conf, 0.98), 0.50), 2),
                "missing_fields": missing,
                "warnings": list(warnings)
            }
            vacancies.append(vac_dict)

        total_openings = sum(v["openings_count"] for v in vacancies) if vacancies else 1
        overall_conf = round(sum(v["confidence_score"] for v in vacancies) / max(len(vacancies), 1), 2) if vacancies else 0.80

        multi_output = {
            "company_name": company_name,
            "location": location,
            "contact_phone": primary_phone,
            "contact_whatsapp": secondary_phone or primary_phone,
            "contact_email": email,
            "website_source": website_source,
            "walk_in_start_date": walk_in_info.get("walk_in_start_date"),
            "walk_in_end_date": walk_in_info.get("walk_in_end_date"),
            "walk_in_date_text": walk_in_info.get("walk_in_date_text"),
            "interview_time": walk_in_info.get("interview_time"),
            "immediate_joiners": walk_in_info.get("immediate_joiners", False),
            "total_vacancies": len(vacancies),
            "total_openings": total_openings,
            "vacancies": vacancies,
            "missing_fields": missing,
            "warnings": warnings
        }

        raw_response = {
            "provider": "RuleBasedFallbackProvider",
            "model": "deterministic-ocr-multijob-v2.0",
            "raw_output": multi_output
        }

        return (multi_output, raw_response, overall_conf, warnings)

class GeminiProvider(AIProvider):
    """
    Google Gemini Multi-Modal Vision API Provider.
    """
    def __init__(self, api_key: str):
        self.api_key = api_key

    def extract_job(
        self,
        text: Optional[str] = None,
        image_bytes: Optional[bytes] = None,
        image_mime: Optional[str] = None
    ) -> Tuple[Dict[str, Any], Dict[str, Any], float, List[str]]:
        multi_res, raw_resp, conf, warns = self.extract_multi_jobs(text, image_bytes, image_mime)
        vacancies = multi_res.get("vacancies", [])
        primary = vacancies[0] if vacancies else {}
        return (primary, raw_resp, conf, warns)

    def extract_multi_jobs(
        self,
        text: Optional[str] = None,
        image_bytes: Optional[bytes] = None,
        image_mime: Optional[str] = None
    ) -> Tuple[Dict[str, Any], Dict[str, Any], float, List[str]]:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={self.api_key}"
            
            parts = [{"text": f"{EXTRACTION_SYSTEM_PROMPT}\n\n<JOB_POST_UNTRUSTED_CONTENT>\n{text or ''}\n</JOB_POST_UNTRUSTED_CONTENT>"}]
            
            if image_bytes:
                b64_image = base64.b64encode(image_bytes).decode("utf-8")
                parts.append({
                    "inline_data": {
                        "mime_type": image_mime or "image/jpeg",
                        "data": b64_image
                    }
                })
                
            payload = {
                "contents": [{"parts": parts}],
                "generationConfig": {
                    "response_mime_type": "application/json",
                    "temperature": 0.1
                }
            }
            
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"}
            )
            
            with urllib.request.urlopen(req, timeout=15) as resp:
                resp_data = json.loads(resp.read().decode("utf-8"))
                text_content = resp_data["candidates"][0]["content"]["parts"][0]["text"]
                extracted = json.loads(text_content)
                vacs = extracted.get("vacancies", [])
                conf = 0.94
                if vacs:
                    conf = sum(float(v.get("confidence_score", 0.94)) for v in vacs) / len(vacs)
                return (extracted, resp_data, round(conf, 2), extracted.get("warnings", []))
        except Exception as e:
            logger.warning(f"Gemini API invocation failed ({e}). Falling back to deterministic OCR extractor.")
            fallback = RuleBasedFallbackProvider()
            extracted, raw_resp, conf, warns = fallback.extract_multi_jobs(text, image_bytes, image_mime)
            warns.append(f"AI Provider fallback used: {e}")
            return (extracted, raw_resp, conf, warns)

def get_ai_provider() -> AIProvider:
    """
    Factory returning the best configured AI Provider with automatic fallback.
    """
    gemini_key = os.getenv("GEMINI_API_KEY")
    if gemini_key:
        return GeminiProvider(api_key=gemini_key)
        
    return RuleBasedFallbackProvider()
