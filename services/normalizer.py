"""
Data Normalization Service for Tiruppur Garment Job Ingestion.
Standardizes company names, departments, job roles, locations, contacts, and salary/exp values.
Preserves raw values while generating clean normalized keys for comparison & indexing.
"""

import re
from typing import Dict, Any, Optional, Tuple
from services.taxonomy import GARMENT_DEPARTMENTS, GARMENT_ROLES, TIRUPPUR_CLUSTERS, TAMIL_GARMENT_KEYWORDS

def normalize_company_name(raw_name: Optional[str]) -> Tuple[str, str]:
    """
    Returns (raw_clean, normalized_key).
    Example: 'ABC Garments Pvt Ltd' -> ('ABC Garments Pvt Ltd', 'abc')
    """
    if not raw_name or not isinstance(raw_name, str):
        return ("", "")
    
    clean_raw = raw_name.strip()
    # Strip sentences and trailing boilerplate if appended
    clean_raw = re.sub(r'\s+(?:is looking for|is hiring|wanted|hiring|walk in|jobs wanted|last date|attn company|for following|immediate openings|interview).*$', '', clean_raw, flags=re.IGNORECASE).strip()
    clean_raw = re.sub(r'^(?:urgent wanted|wanted|walk in|direct|reputed|attn company|we are hiring|job vacancies)\s*[:=-]?\s*', '', clean_raw, flags=re.IGNORECASE).strip()
    clean_raw = re.sub(r'\s+tirupur\s+jobs.*$', '', clean_raw, flags=re.IGNORECASE).strip()
    
    # Filter out template label artifacts
    if clean_raw.lower() in [
        "name & location", "name &     location", "name &       location", "address",
        "company", "unit", "factory", "employer", "direct employer", "garment jobs", "cotton jobs",
        "name and location", "location", "contact", "phone"
    ]:
        return ("", "")

    # Strip common noise and suffixes for comparison key
    lower = clean_raw.lower()
    # Remove punctuation
    cleaned = re.sub(r'[^a-z0-9\s]', ' ', lower)
    # Remove common company entity suffixes
    suffixes = [
        r'\bprivate limited\b', r'\bpvt ltd\b', r'\bltd\b', r'\bllp\b',
        r'\bgarments\b', r'\bgarment\b', r'\bapparel\b', r'\bapparels\b',
        r'\btextiles\b', r'\btextile\b', r'\bexports\b', r'\bexport\b',
        r'\bknitwear\b', r'\bknits\b', r'\bclothing\b', r'\bfashions\b',
        r'\bmills\b', r'\bcreations\b', r'\bindia\b', r'\bindustries\b'
    ]
    for s in suffixes:
        cleaned = re.sub(s, ' ', cleaned)
    
    # Merge single letter initials like 'a b c' into 'abc'
    cleaned = re.sub(r'(?<=\b[a-z])\s+(?=[a-z]\b)', '', cleaned)
    
    norm_key = re.sub(r'\s+', ' ', cleaned).strip()
    if not norm_key:
        norm_key = re.sub(r'\s+', ' ', clean_raw.lower()).strip()
        
    return clean_raw, norm_key

def normalize_department(raw_dept: Optional[str], text_context: Optional[str] = None) -> str:
    """
    Maps raw department or contextual text to a canonical DigiGarment department.
    """
    if not raw_dept and not text_context:
        return "Other"
        
    combined = f"{raw_dept or ''} {text_context or ''}".lower()
    
    # Priority matching
    if any(k in combined for k in ["it assistant", "it executive", "it admin", "network admin", "software", "information tech", " it "]):
        return "IT"
    if any(k in combined for k in ["training manager", "sewing trainer", "sewing", "stitching", "tailor", "line supervisor", "தையல்"]):
        return "Sewing"
    if any(k in combined for k in ["store", "warehouse", "inventory", "stock", "fabric deo", "store deo", "deo", "data entry"]):
        return "Stores"
    if any(k in combined for k in ["merchandis", "sampling", "buyer", "costing", "tna", "மெர்ச்சண்டைசர்"]):
        return "Merchandising"
    if any(k in combined for k in ["quality", "qc", "qa", "checking", "audit", "aql", "defect", "குவாலிட்டி"]):
        return "Quality"
    if any(k in combined for k in ["cutting", "pattern", "cad", "marker", "grading", "கட்டிங்"]):
        return "Cutting"
    if any(k in combined for k in ["finishing", "ironing", "packing", "packing incharge", "அயர்னிங்", "பேக்கிங்"]):
        return "Finishing"
    if any(k in combined for k in ["printing", "screen print", "rotary", "curing"]):
        return "Printing"
    if any(k in combined for k in ["embroidery", "emb", "computer embroidery"]):
        return "Embroidery"
    if any(k in combined for k in ["knitting", "circular knit", "flat knit"]):
        return "Knitting"
    if any(k in combined for k in ["dyeing", "processing", "bleaching"]):
        return "Dyeing"
    if any(k in combined for k in ["ppc", "planning", "production control"]):
        return "Production Planning"
    if any(k in combined for k in ["account", "tally", "gst", "billing"]):
        return "Accounts"
    if any(k in combined for k in ["maintenance", "mechanic", "electrician"]):
        return "Maintenance"
    if any(k in combined for k in ["hr", "human resource", "admin", "recruiter", "time office"]):
        return "HR"
    if any(k in combined for k in ["production", "floor supervisor", "production supervisor", "production manager"]):
        return "Production"

    # Match against canonical list if exact
    if raw_dept:
        for d in GARMENT_DEPARTMENTS:
            if d.lower() == raw_dept.strip().lower():
                return d
                
    return "Production"

def normalize_job_role(raw_role: Optional[str], dept: str = "Production") -> Tuple[str, str]:
    """
    Returns (clean_raw_role, canonical_role).
    Example: 'Sr. Merchandiser (Woven)' -> ('Sr. Merchandiser (Woven)', 'Senior Merchandiser')
    """
    if not raw_role or not isinstance(raw_role, str):
        return ("Garment Vacancy", "Garment Executive")
        
    clean_raw = raw_role.strip()
    lower = clean_raw.lower()
    
    # Specific canonical role mappings
    if "merchandising manager" in lower or "merchandise manager" in lower:
        return (clean_raw, "Merchandising Manager")
    if "senior merchandiser" in lower or "sr. merchandiser" in lower or "sr merchandiser" in lower or "lead merchandiser" in lower:
        return (clean_raw, "Senior Merchandiser")
    if "assistant merchandiser" in lower or "asst. merchandiser" in lower or "asst merchandiser" in lower:
        return (clean_raw, "Assistant Merchandiser")
    if "junior merchandiser" in lower or "jr. merchandiser" in lower or "jr merchandiser" in lower:
        return (clean_raw, "Junior Merchandiser")
    if "sampling merchandiser" in lower:
        return (clean_raw, "Sampling Merchandiser")
    if "merchandiser" in lower:
        return (clean_raw, "Merchandiser")
    if "costing executive" in lower or "costing manager" in lower:
        return (clean_raw, "Costing Executive")
        
    if "training manager" in lower:
        return (clean_raw, "Training Manager")
    if "it assistant" in lower or "it executive" in lower or "it admin" in lower:
        return (clean_raw, "IT Assistant")
    if "fabric deo" in lower:
        return (clean_raw, "Fabric DEO")
    if "deo" in lower or "data entry" in lower:
        return (clean_raw, "Data Entry Operator (DEO)")
        
    if "qa manager" in lower or "quality manager" in lower:
        return (clean_raw, "QA Manager")
    if "quality auditor" in lower or "qc auditor" in lower:
        return (clean_raw, "Quality Auditor")
    if "checking supervisor" in lower or "checking incharge" in lower:
        return (clean_raw, "Checking Supervisor")
    if "quality supervisor" in lower or "qc supervisor" in lower:
        return (clean_raw, "Quality Supervisor")
    if "line qc" in lower or "inline qc" in lower:
        return (clean_raw, "Line QC")
    if "quality inspector" in lower or "qc inspector" in lower or "quality checker" in lower or "qc checker" in lower or "குவாலிட்டி" in lower:
        return (clean_raw, "Quality Inspector")
    if "quality" in lower or "qc" in lower or "qa" in lower:
        return (clean_raw, "Quality Inspector")
        
    if "cad pattern" in lower or "optitex" in lower or "gerber" in lower or "lectra" in lower:
        return (clean_raw, "CAD Pattern Master")
    if "pattern master" in lower:
        return (clean_raw, "Pattern Master")
    if "cutting master" in lower or "cutting incharge" in lower or "கட்டிங் மாஸ்டர்" in lower:
        return (clean_raw, "Cutting Master")
        
    if "production manager" in lower:
        return (clean_raw, "Production Manager")
    if "production supervisor" in lower or "floor supervisor" in lower:
        return (clean_raw, "Production Supervisor")
    if "line supervisor" in lower or "தையல் சூப்பர்வைசர்" in lower:
        return (clean_raw, "Line Supervisor")
    if "industrial engineer" in lower or "ie executive" in lower or "work study" in lower:
        return (clean_raw, "Industrial Engineer (IE)")
    if "tailor" in lower or "sewing machine operator" in lower:
        return (clean_raw, "Sewing Machine Operator")
        
    if "finishing supervisor" in lower or "finishing incharge" in lower:
        return (clean_raw, "Finishing Supervisor")
    if "packing supervisor" in lower or "packing incharge" in lower:
        return (clean_raw, "Packing Supervisor")
        
    if "printing master" in lower:
        return (clean_raw, "Printing Master")
    if "embroidery master" in lower or "computer embroidery" in lower:
        return (clean_raw, "Computer Embroidery Operator")
        
    if "ppc" in lower or "production planning" in lower:
        return (clean_raw, "Production Planning & Control (PPC) Executive")
    if "store keeper" in lower or "store incharge" in lower:
        return (clean_raw, "Store Keeper")
    # Accounts & Administration
    if "accounts executive" in lower or "account executive" in lower:
        return (clean_raw, "Accounts Executive")
    if "accountant" in lower:
        return (clean_raw, "Accountant")
    if "hr executive" in lower or "hr manager" in lower or "human resource" in lower:
        return (clean_raw, "HR Executive")
        
    if "mechanic" in lower:
        return (clean_raw, "Sewing Machine Mechanic")
        
    return (clean_raw, clean_raw.title())

def parse_openings_count(raw_text: Optional[str]) -> int:
    """
    Parses opening / vacancy count from strings like:
    '- 1 No.', '- 2 Nos.', '2 Nos', '5 Nos.', '3 Vacancies', 'Openings: 5'
    Returns an integer >= 1.
    """
    if not raw_text or not isinstance(raw_text, str):
        return 1
    
    text = raw_text.strip()
    
    # 1. Match patterns like '1 No', '2 Nos', '2 Nos.', '- 5 Nos'
    nos_match = re.search(r'[-–—:]?\s*(\d+)\s*(?:nos?\.?|no\.?|posts?|vacanc(?:y|ies)|openings?|positions?)\b', text, re.IGNORECASE)
    if nos_match:
        try:
            val = int(nos_match.group(1))
            if 1 <= val <= 500:
                return val
        except (ValueError, TypeError):
            pass
            
    # 2. Match patterns like 'Openings: 5', 'Vacancies: 3'
    lbl_match = re.search(r'\b(?:openings?|vacanc(?:y|ies)|posts?|positions?|count)\s*[:=-]\s*(\d+)\b', text, re.IGNORECASE)
    if lbl_match:
        try:
            val = int(lbl_match.group(1))
            if 1 <= val <= 500:
                return val
        except (ValueError, TypeError):
            pass
            
    return 1

def parse_walk_in_details(raw_text: Optional[str]) -> Dict[str, Any]:
    """
    Extracts walk-in interview date range, interview timing, and immediate joiner preferences.
    """
    res = {
        "is_walk_in": False,
        "walk_in_start_date": None,
        "walk_in_end_date": None,
        "walk_in_date_text": None,
        "interview_time": None,
        "immediate_joiners": False
    }
    if not raw_text or not isinstance(raw_text, str):
        return res
        
    text = raw_text.strip()
    lower = text.lower()
    
    if any(k in lower for k in ["walk-in", "walk in", "நேரடி நேர்காணல்", "walkin", "interview date"]):
        res["is_walk_in"] = True
        
    if "immediate joiner" in lower or "immediate joiners" in lower:
        res["immediate_joiners"] = True
        
    # Match date ranges like 24.08.2026 to 29.08.2026 or 24/08/2026 - 29/08/2026 or 24-08-2026 TO 29-08-2026
    date_range_match = re.search(
        r'(\d{1,2}[\.\/\-]\d{1,2}[\.\/\-]\d{2,4})\s*(?:to|[-–—])\s*(\d{1,2}[\.\/\-]\d{1,2}[\.\/\-]\d{2,4})',
        text, re.IGNORECASE
    )
    if date_range_match:
        d1_raw, d2_raw = date_range_match.group(1), date_range_match.group(2)
        res["walk_in_date_text"] = f"{d1_raw} to {d2_raw}"
        res["is_walk_in"] = True
        
        def _parse_to_iso(d_str):
            parts = re.split(r'[\.\/\-]', d_str)
            if len(parts) == 3:
                day, month, year = int(parts[0]), int(parts[1]), int(parts[2])
                if year < 100:
                    year += 2000
                if 1 <= month <= 12 and 1 <= day <= 31:
                    return f"{year:04d}-{month:02d}-{day:02d}"
            return None
            
        res["walk_in_start_date"] = _parse_to_iso(d1_raw)
        res["walk_in_end_date"] = _parse_to_iso(d2_raw)

    # Match interview time: e.g. 10:00 AM - 5:00 PM or 10 AM to 5 PM
    time_match = re.search(r'(\d{1,2}(?::\d{2})?\s*(?:am|pm|a\.m\.|p\.m\.)\s*(?:[-–—]|to)\s*\d{1,2}(?::\d{2})?\s*(?:am|pm|a\.m\.|p\.m\.))', text, re.IGNORECASE)
    if time_match:
        res["interview_time"] = time_match.group(1).upper()
        res["is_walk_in"] = True
        
    return res

def parse_gender_requirement(raw_text: Optional[str]) -> str:
    """
    Parses gender requirements like '(Male)', '(Female)', '(Male/Female)', 'Ladies only'.
    """
    if not raw_text or not isinstance(raw_text, str):
        return "Male/Female"
        
    lower = raw_text.strip().lower()
    
    if "male/female" in lower or "male / female" in lower or "male or female" in lower or "any" in lower:
        return "Male/Female"
    if "(male)" in lower or "male only" in lower or "gents only" in lower or "ஆண்கள்" in lower:
        return "Male"
    if "(female)" in lower or "female only" in lower or "ladies only" in lower or "பெண்கள்" in lower:
        return "Female"
        
    return "Male/Female"

def parse_role_skills_and_requirements(raw_text: Optional[str], canonical_role: Optional[str] = None) -> Tuple[List[str], Optional[str]]:
    """
    Extracts role-specific technical skills and verbatim requirements.
    Ensures technical skills (e.g. Tally Prime, GST, TDS) are NOT cross-contaminated across roles.
    """
    if not raw_text or not isinstance(raw_text, str):
        return ([canonical_role] if canonical_role else [], None)
        
    skills = []
    lower = raw_text.lower()
    
    # Specific skills detection
    if "tally prime" in lower or "tally" in lower:
        skills.append("Tally Prime")
    if "gst" in lower:
        skills.append("GST")
    if "tds" in lower:
        skills.append("TDS")
    if "optitex" in lower:
        skills.append("Optitex CAD")
    if "gerber" in lower:
        skills.append("Gerber CAD")
    if "lectra" in lower:
        skills.append("Lectra CAD")
    if "excel" in lower or "ms excel" in lower or "advanced excel" in lower:
        skills.append("MS Excel")
    if "fastreact" in lower:
        skills.append("FastReact")
        
    # Extract requirement sentence if present
    req_match = re.search(r'(?:knowledge\s+in\s+[^.\n]+|knowledge\s+of\s+[^.\n]+|experience\s+in\s+[^.\n]+|proficiency\s+in\s+[^.\n]+)', raw_text, re.IGNORECASE)
    req_text = req_match.group(0).strip() if req_match else None
    
    if canonical_role and canonical_role not in skills:
        skills.insert(0, canonical_role)
        
    return (skills, req_text)

def extract_all_phone_numbers(raw_text: Optional[str]) -> List[str]:
    """
    Extracts all valid Indian 10-digit mobile numbers from raw text in order of appearance.
    """
    if not raw_text or not isinstance(raw_text, str):
        return []
        
    clean_text = raw_text.replace("-", " ")
    # Match standard formats with spaces or without
    candidates = re.findall(r'(?:\+91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}', clean_text)
    if not candidates:
        candidates = re.findall(r'\b[6-9]\d{9}\b', clean_text)
        
    res = []
    seen = set()
    for c in candidates:
        norm = normalize_phone_number(c)
        if norm and norm not in seen:
            seen.add(norm)
            res.append(norm)
            
    return res

def normalize_location(raw_loc: Optional[str]) -> str:
    """
    Standardizes location string to include Tiruppur cluster.
    Isolates actual street/area/cluster and eliminates header/date/category noise.
    Example: '34-A, P.N. Road, 2nd Street, Tiruppur - 641602' -> '34-A, P.N. Road, 2nd Street, Tiruppur - 641602'
    """
    if not raw_loc or not isinstance(raw_loc, str):
        return "Tiruppur, Tamil Nadu"
        
    text = raw_loc.strip()
    
    # 1. Clean out category headers, back links, dates, and noise words
    noise_patterns = [
        r'Back\s*Garments?\s*Jobs',
        r'Garments?\s*Jobs',
        r'\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}',
        r'Job\s*Description\s*[:=-]?',
        r'Company\s*Details\s*[:=-]?',
        r'Contact\s*Details\s*[:=-]?',
        r'Interview\s*Time\s*[:=-]?',
        r'https?://[^\s]+',
        r'\b\d{10}\b'
    ]
    for np in noise_patterns:
        text = re.sub(np, ' ', text, flags=re.IGNORECASE)
        
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    
    # If multiple lines, pick the line most likely to contain an address
    chosen_line = ""
    for l in lines:
        lower_l = l.lower()
        if any(k in lower_l for k in ["road", "street", "nagar", "palayam", "tiruppur", "tirupur", "palladam", "avinashi", "dharapuram", "veerapandi", "641", "near", "opposite", "s.f.", "sf no"]):
            chosen_line = l
            break
    if not chosen_line and lines:
        chosen_line = lines[0]
        
    clean_raw = re.sub(r'^[,\s\-]+|[,\s\-]+$', '', chosen_line).strip()
    if not clean_raw or len(clean_raw) < 3 or clean_raw.lower() in ["garment jobs", "tiruppur", "tamil nadu"]:
        return "Tiruppur, Tamil Nadu"
        
    lower = clean_raw.lower()
    
    if lower == "nap" or "nap" in lower.split():
        return "Netaji Apparel Park, Tiruppur"
        
    # Check if multiple cluster / area keywords exist in context
    found_areas = []
    area_keywords = [
        "Kangayam Road", "Vijayapuram", "Avinashi Road", "Palladam Road", "Mangalam Road",
        "Uthukuli Road", "Dharapuram Road", "Angeripalayam", "Veerapandi", "Anupparpalayam",
        "Perumanallur", "Kunnathur", "Netaji Apparel Park", "SIDCO", "Rayapuram", "Sirupooluvapatti",
        "P.N. Road", "PN Road", "Boyampalayam", "Kuppandampalayam", "Nallur", "Neruperichal"
    ]
    for area in area_keywords:
        if area.lower() in lower:
            found_areas.append(area)
            
    if found_areas:
        # If clean_raw already contains full street address, preserve it
        if any(k in lower for k in ["street", "door", "no.", "no:", "sf", "s.f", "641"]):
            return clean_raw
        if "tiruppur" not in lower and "tirupur" not in lower:
            found_areas.append("Tiruppur")
        elif not any("tiruppur" in a.lower() for a in found_areas):
            found_areas.append("Tiruppur")
        return ", ".join(found_areas)
        
    matched_cluster = None
    for cluster in TIRUPPUR_CLUSTERS:
        if cluster.lower() in lower:
            matched_cluster = cluster
            break
            
    if matched_cluster:
        if any(k in lower for k in ["street", "door", "no.", "no:", "sf", "s.f", "641"]):
            return clean_raw
        if "tiruppur" in matched_cluster.lower() or "tirupur" in matched_cluster.lower():
            return matched_cluster
        return f"{matched_cluster}, Tiruppur"
        
    if "tirupur" in lower or "tiruppur" in lower:
        return clean_raw
        
    return f"{clean_raw}, Tiruppur"

def normalize_phone_number(raw_phone: Optional[str]) -> Optional[str]:
    """
    Extracts 10-digit mobile number and returns standardized format '+91 XXXXX XXXXX'.
    """
    if not raw_phone or not isinstance(raw_phone, str):
        return None
        
    digits = re.sub(r'[^0-9]', '', raw_phone)
    if not digits:
        return None
        
    # If starts with 91 and has 12 digits
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
        
    if len(digits) >= 10:
        ten_digit = digits[-10:]
        return f"+91 {ten_digit[:5]} {ten_digit[5:]}"
        
    return None

def parse_salary_range(raw_text: Optional[str]) -> Tuple[Optional[float], Optional[float], Optional[str]]:
    """
    Parses salary text into (min_salary, max_salary, display_text).
    Example: '25K-30K' -> (25000.0, 30000.0, '₹25,000 - ₹30,000 / month')
    """
    if not raw_text or not isinstance(raw_text, str):
        return (None, None, None)
        
    text = raw_text.strip()
    
    # Match '25k - 30k' or '25K to 30K'
    k_match = re.search(r'(?:₹|rs\.?|inr)?\s*(\d+)\s*[kK]\s*(?:-|to)\s*(?:₹|rs\.?|inr)?\s*(\d+)\s*[kK]', text, re.IGNORECASE)
    if k_match:
        s_min = float(k_match.group(1)) * 1000
        s_max = float(k_match.group(2)) * 1000
        return (s_min, s_max, f"₹{int(s_min):,} - ₹{int(s_max):,} / month")
        
    # Match '25,000 - 30,000' or '₹25,000 - ₹30,000'
    num_match = re.search(r'(?:₹|rs\.?|inr)?\s*(\d{1,2},?\d{3,5})\s*(?:-|to)\s*(?:₹|rs\.?|inr)?\s*(\d{1,2},?\d{3,5})', text, re.IGNORECASE)
    if num_match:
        s_min = float(re.sub(r'[^0-9]', '', num_match.group(1)))
        s_max = float(re.sub(r'[^0-9]', '', num_match.group(2)))
        return (s_min, s_max, f"₹{int(s_min):,} - ₹{int(s_max):,} / month")
        
    # Single figure '30,000' or '30k'
    single_k = re.search(r'(\d+)\s*[kK]', text)
    if single_k:
        val = float(single_k.group(1)) * 1000
        return (val, None, f"₹{int(val):,} / month")
        
    # Check if text explicitly mentions negotiable or norms
    lower = text.lower()
    if any(k in lower for k in ["negotiable", "best in industry", "as per norms", "industry standard", "attractive salary", "தகுதிக்கேற்ப"]):
        return (None, None, "Salary Negotiable")
        
    return (None, None, None)

def parse_experience_range(raw_text: Optional[str]) -> Tuple[int, Optional[int]]:
    """
    Parses experience text into (min_exp, max_exp).
    Example: '2-4 years' -> (2, 4), '3+ years' -> (3, None), 'Fresher' -> (0, 1)
    """
    if not raw_text or not isinstance(raw_text, str):
        return (0, None)
        
    lower = raw_text.strip().lower()
    if "fresher" in lower or "0 year" in lower or "no exp" in lower:
        return (0, 1)
        
    # Match experience ranges like '2-4 years', '3 to 5 yrs', '2 - 4' (1-2 digits only)
    range_match = re.search(r'\b([0-9]{1,2})\s*(?:-|to)\s*([0-9]{1,2})\b', lower)
    if range_match:
        e1, e2 = int(range_match.group(1)), int(range_match.group(2))
        if e1 <= 40 and e2 <= 40:
            return (min(e1, e2), max(e1, e2))
        
    plus_match = re.search(r'\b([0-9]{1,2})\s*\+', lower)
    if plus_match:
        e = int(plus_match.group(1))
        if e <= 40:
            return (e, None)
        
    single_num = re.search(r'\b([0-9]{1,2})\s*(?:years?|yrs?|yr|ஆண்டுகள்)\b', lower)
    if single_num:
        e = int(single_num.group(1))
        if e <= 40:
            return (e, None)
        
    return (0, None)
