"""
Company Matching & Entity Resolution Service.
Resolves incoming raw company names against existing registered companies.
Uses exact match, normalized suffix-stripped key, phone/domain matching, and fuzzy Levenshtein ratio.
"""

import re
import difflib
from typing import Dict, Any, Optional, List, Tuple
from services.normalizer import normalize_company_name

class CompanyMatcher:
    def __init__(self, existing_companies: List[Dict[str, Any]]):
        self.companies = existing_companies

    def match_company(
        self,
        raw_company_name: Optional[str],
        phone: Optional[str] = None,
        email: Optional[str] = None
    ) -> Tuple[Optional[Dict[str, Any]], float, str]:
        """
        Attempts to match raw company against existing companies list.
        Returns: (matched_company_dict_or_None, match_confidence, match_reason)
        """
        if not raw_company_name and not phone and not email:
            return (None, 0.0, "No company or contact criteria provided.")

        clean_raw, norm_key = normalize_company_name(raw_company_name)

        # 1. Contact number anchor match (Highest confidence: 95%)
        if phone:
            clean_digits = re.sub(r'[^0-9]', '', phone)[-10:]
            for comp in self.companies:
                comp_phone = comp.get("contact_phone")
                if comp_phone and clean_digits in re.sub(r'[^0-9]', '', comp_phone):
                    return (comp, 0.95, f"Matched via verified contact phone ({phone})")

        # 2. Exact name match (95%)
        for comp in self.companies:
            if comp.get("name", "").strip().lower() == clean_raw.lower():
                return (comp, 0.95, "Exact company name match")

        # 3. Normalized key match (88%)
        if norm_key:
            for comp in self.companies:
                _, comp_norm_key = normalize_company_name(comp.get("name"))
                if comp_norm_key and (comp_norm_key == norm_key or norm_key in comp_norm_key or comp_norm_key in norm_key):
                    return (comp, 0.88, f"Normalized key match ('{norm_key}')")

        # 4. Fuzzy similarity matching (70% - 85%)
        if clean_raw:
            best_match = None
            best_score = 0.0
            for comp in self.companies:
                score = difflib.SequenceMatcher(None, clean_raw.lower(), comp.get("name", "").lower()).ratio()
                if score > best_score:
                    best_score = score
                    best_match = comp

            if best_score >= 0.80 and best_match:
                return (best_match, round(best_score, 2), f"Fuzzy similarity ({int(best_score*100)}%)")

        return (None, 0.0, "New unique company profile suggested.")
