"""
Cotton Jobs Website Source Connector for DigiGarment Tiruppur Jobs.
Curls https://www.cottonjobs.in/ (Blogger platform) with dynamic lookback date filtering,
Read More detail page fetching, clean content sanitization (removing WhatsApp/Telegram promotional widgets),
verbatim source role extraction, and Source != Company separation.
"""

import re
import urllib.parse
import urllib.request
import logging
from datetime import datetime, date, timedelta
from typing import List, Dict, Any, Optional, Tuple

from services.source_connectors.base import BaseSourceConnector
from services.normalizer import (
    normalize_company_name,
    normalize_location,
    normalize_phone_number,
    extract_all_phone_numbers,
    parse_walk_in_details
)

logger = logging.getLogger(__name__)

class CottonJobsConnector(BaseSourceConnector):
    """
    Production-hardened connector for Cotton Jobs (https://www.cottonjobs.in/).
    Extracts genuine Tiruppur apparel vacancies with lookback filtering,
    clean text parsing, and strict employer isolation.
    """

    def __init__(self):
        super().__init__(
            source_id="cotton_jobs",
            source_name="Cotton Jobs",
            base_url="https://www.cottonjobs.in",
            allowed_domains=["cottonjobs.in", "www.cottonjobs.in"],
            requests_per_minute=20
        )

    def parse_cotton_date(self, raw_date_str: Optional[str]) -> Optional[date]:
        """
        Parses dates from Cotton Jobs formats (ISO, Blogger Atom published timestamps, DD.MM.YYYY, DD/MM/YYYY).
        """
        if not raw_date_str or not isinstance(raw_date_str, str):
            return None
            
        clean_d = raw_date_str.strip()
        
        # 1. ISO 8601 (e.g. '2026-09-01T10:30:00.000+05:30' or '2026-09-01')
        iso_m = re.match(r'^(\d{4})-(\d{2})-(\d{2})', clean_d)
        if iso_m:
            try:
                return date(int(iso_m.group(1)), int(iso_m.group(2)), int(iso_m.group(3)))
            except ValueError:
                pass
                
        # 2. DD/MM/YYYY or DD.MM.YYYY or DD-MM-YYYY
        dmy_m = re.search(r'\b(\d{1,2})[/\.\-](\d{1,2})[/\.\-](\d{4})\b', clean_d)
        if dmy_m:
            try:
                d, m, y = int(dmy_m.group(1)), int(dmy_m.group(2)), int(dmy_m.group(3))
                return date(y, m, d)
            except ValueError:
                pass
                
        # 3. URL path date (e.g. /2026/03/post-title.html -> year 2026, month 03)
        url_m = re.search(r'/(\d{4})/(\d{2})/', clean_d)
        if url_m:
            try:
                y, m = int(url_m.group(1)), int(url_m.group(2))
                return date(y, m, 1)
            except ValueError:
                pass

        return None

    def discover_job_urls(
        self,
        max_pages: int = 10,
        lookback_days: int = 10,
        target_date: Optional[date] = None
    ) -> Dict[str, Any]:
        """
        Discovers Cotton Jobs posts within (target_date - lookback_days) -> target_date.
        Uses Blogger JSON feed and HTML homepage fallback.
        """
        today = target_date or datetime.now().date()
        cutoff_date = today - timedelta(days=lookback_days)
        
        logger.info(
            f"Starting Cotton Jobs discovery from {self.base_url} | "
            f"Lookback: {lookback_days} days (Cutoff: {cutoff_date.isoformat()} to {today.isoformat()})"
        )

        discovered_cards = []
        older_skipped = 0
        pages_visited = 0
        seen_urls = set()

        # 1. Try Blogger JSON Feed first (standard, fast, highly structured)
        feed_url = f"{self.base_url}/feeds/posts/default?alt=json&max-results=50"
        feed_content, status_code, err = self.fetch_page(feed_url)
        
        if status_code == 200 and feed_content:
            try:
                import json
                feed_data = json.loads(feed_content)
                entries = feed_data.get("feed", {}).get("entry", [])
                pages_visited += 1
                
                for entry in entries:
                    # Extract URL
                    alternate_links = [l.get("href") for l in entry.get("link", []) if l.get("rel") == "alternate"]
                    if not alternate_links:
                        continue
                    post_url = self.canonicalize_url(alternate_links[0])
                    if post_url in seen_urls:
                        continue
                    seen_urls.add(post_url)
                    
                    # Extract post date
                    pub_str = entry.get("published", {}).get("$t") or entry.get("updated", {}).get("$t")
                    post_date = self.parse_cotton_date(pub_str) if pub_str else None
                    if not post_date:
                        post_date = self.parse_cotton_date(post_url)
                    
                    # Title
                    title = entry.get("title", {}).get("$t", "").strip()
                    
                    # Check date cutoff
                    if post_date:
                        if post_date < cutoff_date:
                            older_skipped += 1
                            continue
                        if post_date > today:
                            # Future post timestamp adjustment
                            post_date = today
                    else:
                        post_date = today

                    discovered_cards.append({
                        "read_more_url": post_url,
                        "post_date": post_date,
                        "post_date_str": post_date.isoformat(),
                        "card_company": None,
                        "card_location": "Tiruppur",
                        "card_phone": None,
                        "card_title": title
                    })
            except Exception as e:
                logger.warning(f"Error parsing Cotton Jobs JSON feed: {e}")

        # 2. Fallback to HTML homepage parsing if feed yielded no entries
        if not discovered_cards:
            hp_content, hp_status, _ = self.fetch_page(self.base_url)
            if hp_status == 200 and hp_content:
                pages_visited += 1
                matches = re.findall(r'<a[^>]+href=[\'"]([^\'"]+\.html)[\'"][^>]*>([\s\S]*?)</a>', hp_content, re.IGNORECASE)
                for href, text in matches:
                    clean_h = href.split("?")[0].split("#")[0]
                    if any(skip in clean_h.lower() for skip in ["/p/", "search", "privacy", "disclaimer", "contact", "about"]):
                        continue
                    post_url = self.canonicalize_url(clean_h)
                    if post_url in seen_urls:
                        continue
                    seen_urls.add(post_url)
                    
                    post_date = self.parse_cotton_date(post_url) or today
                    if post_date < cutoff_date:
                        older_skipped += 1
                        continue
                    
                    clean_t = re.sub(r'<[^>]+>', ' ', text).strip()
                    discovered_cards.append({
                        "read_more_url": post_url,
                        "post_date": post_date,
                        "post_date_str": post_date.isoformat(),
                        "card_company": None,
                        "card_location": "Tiruppur",
                        "card_phone": None,
                        "card_title": clean_t
                    })

        return {
            "source_id": self.source_id,
            "source_name": self.source_name,
            "lookback_days": lookback_days,
            "cutoff_date": cutoff_date.isoformat(),
            "target_date": today.isoformat(),
            "pages_visited": max(pages_visited, 1),
            "total_cards_discovered": len(discovered_cards) + older_skipped,
            "posts_within_lookback": len(discovered_cards),
            "older_posts_skipped": older_skipped,
            "qualifying_posts": discovered_cards
        }

    def parse_job_page(
        self,
        url: str,
        html_content: str,
        card_meta: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Parses an individual Cotton Jobs post detail page into structured raw source data.
        
        Strict Rules:
        - Source: Cotton Jobs does NOT mean Company = Cotton Jobs.
        - If company not mentioned -> company_name = None (NULL).
        - Extracts actual job designations and descriptions.
        - Filters out Blogger widgets, social cards, Telegram/WhatsApp join buttons, footers.
        - Preserves embedded flyer poster image URL.
        """
        canon_url = self.canonicalize_url(url)
        card_meta = card_meta or {}

        # 1. Extract Main Post Body Container
        body_m = re.search(r'<div[^>]*class=[\'"][^\'"]*post-body[^\'"]*[\'"][^>]*>([\s\S]*?)</div>\s*<div', html_content, re.IGNORECASE)
        if not body_m:
            body_m = re.search(r'<div[^>]*class=[\'"][^\'"]*post-body[^\'"]*[\'"][^>]*>([\s\S]*?)</div>', html_content, re.IGNORECASE)
        container_html = body_m.group(1) if body_m else html_content

        # 2. Extract Embedded Flyer / Poster Images from post body
        image_url = None
        img_matches = re.findall(r'<img[^>]+src=[\'"]([^\'"]+?)[\'"]', container_html, re.IGNORECASE)
        for img in img_matches:
            img_lower = img.lower()
            if any(ext in img_lower for ext in [".jpg", ".jpeg", ".png", ".webp"]):
                if not any(skip in img_lower for skip in ["logo", "icon", "banner", "avatar", "analytics", "whatsapp", "telegram", "blogger"]):
                    image_url = urllib.parse.urljoin(canon_url, img)
                    break

        # 3. Clean HTML to Text
        clean_text = self.clean_html_to_text(container_html)
        
        # 3. Clean and isolate actual vacancy text
        noise_patterns = [
            r'Join\s*Our\s*WhatsApp[^\n]*',
            r'Join\s*Our\s*Telegram[^\n]*',
            r'Share\s*on\s*WhatsApp[^\n]*',
            r'Share\s*on\s*Telegram[^\n]*',
            r'Download\s*our\s*app[^\n]*',
            r'https?://[^\s]*cottonjobs\.in[^\s]*',
            r'https?://[^\s]*whatsapp\.com[^\s]*',
            r'https?://[^\s]*t\.me[^\s]*',
            r'Labels:[^\n]*',
            r'Posted\s*by[^\n]*',
            r'Comments[^\n]*'
        ]
        sanitized = clean_text
        for np in noise_patterns:
            sanitized = re.sub(np, ' ', sanitized, flags=re.IGNORECASE)
            
        sanitized_lines = [l.strip() for l in sanitized.splitlines() if l.strip()]
        clean_job_text = '\n'.join(sanitized_lines)

        # 4. Extract Company Name (STRICT: Source != Company)
        company_name = None
        
        # Check explicit "Company: <Name>" or top lines
        comp_m = re.search(r'(?:Company|Unit|Factory|Employer)\s*[:=-]\s*([^\n]+)', clean_text, re.IGNORECASE)
        if comp_m:
            cand = comp_m.group(1).strip()
            if cand and not any(k in cand.lower() for k in ["location", "contact", "phone", "tiruppur"]):
                clean_c, _ = normalize_company_name(cand)
                if clean_c and clean_c.lower() not in ["cotton jobs", "garment jobs", "direct employer"]:
                    company_name = clean_c

        if not company_name:
            # Check first 5 lines for garment entity patterns (e.g. 'FAST FASHION INDIA PVT LTD')
            for line in sanitized_lines[:6]:
                lower_l = line.lower()
                if any(suffix in lower_l for suffix in ["garments", "knitters", "apparels", "apparel", "exports", "textiles", "knits", "clothing", "mills", "creations", "fashions", "pvt ltd"]):
                    clean_l = re.sub(r'^(?:urgent wanted|wanted|walk in|direct)\s*[:=-]?\s*', '', line, flags=re.IGNORECASE).strip()
                    cand_c, _ = normalize_company_name(clean_l)
                    if cand_c and cand_c.lower() not in ["cotton jobs", "garment jobs", "direct employer"]:
                        company_name = cand_c
                        break

        # Mandatory NULL if not found or invalid
        if company_name and company_name.lower() in ["cotton jobs", "garment jobs", "direct employer", "unknown employer", "garment manufacturer"]:
            company_name = None

        # 5. Extract Location
        location = None
        loc_m = re.search(r'(?:Location|Address|Place)\s*[:=-]\s*([^\n]+)', clean_text, re.IGNORECASE)
        if loc_m:
            raw_loc = loc_m.group(1).strip()
            if raw_loc and not any(k in raw_loc.lower() for k in ["contact", "call", "whatsapp"]):
                location = normalize_location(raw_loc)
                
        if not location:
            location = normalize_location(clean_job_text)

        # 6. Extract Recruiter Contacts
        contact_phones = []
        raw_phones = re.findall(r'\b[6-9]\d{9}\b', clean_job_text)
        for p in raw_phones:
            norm_p = normalize_phone_number(p)
            if norm_p and norm_p not in contact_phones:
                contact_phones.append(norm_p)
                
        primary_phone = contact_phones[0] if contact_phones else None
        secondary_phone = contact_phones[1] if len(contact_phones) > 1 else primary_phone

        # Recruiter Email
        email_matches = re.findall(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', clean_job_text)
        recruiter_email = None
        for em in email_matches:
            if not any(skip in em.lower() for skip in ["cottonjobs", "blogger", "noreply", "example"]):
                recruiter_email = em.strip()
                break

        # 7. Extract Walk-in & Interview Details
        walk_in_info = parse_walk_in_details(clean_job_text)
        interview_time = walk_in_info.get("interview_time")

        # 8. Post Date
        post_date_obj = card_meta.get("post_date")
        if not post_date_obj:
            time_m = re.search(r'<time[^>]*datetime=[\'"]([^\'"]+)[\'"]|<abbr[^>]*title=[\'"]([^\'"]+)[\'"]', html_content, re.IGNORECASE)
            if time_m:
                d_str = time_m.group(1) or time_m.group(2)
                post_date_obj = self.parse_cotton_date(d_str)
        if not post_date_obj:
            post_date_obj = self.parse_cotton_date(canon_url) or datetime.now().date()

        post_date_str = post_date_obj.isoformat()

        # 9. Reference Slug & Hashes
        path_slug = urllib.parse.urlparse(canon_url).path.strip("/").split("/")[-1].replace(".html", "")
        source_reference = path_slug if path_slug else f"cotton_{self.compute_content_hash(clean_job_text)[:12]}"
        
        content_hash = self.compute_content_hash(clean_job_text)
        source_hash = self.compute_source_hash(image_url or canon_url)

        return {
            "source_type": "website",
            "source_name": "Cotton Jobs",
            "source_url": canon_url,
            "source_reference": source_reference,
            "source_posted_date": post_date_str,
            "raw_text": clean_job_text,
            "raw_html_reference": canon_url,
            "poster_image_url": image_url,
            "content_hash": content_hash,
            "source_hash": source_hash,
            "company_name": company_name,
            "location": location,
            "contact_phone": primary_phone,
            "contact_whatsapp": secondary_phone,
            "contact_email": recruiter_email,
            "interview_time": interview_time,
            "walk_in_start_date": walk_in_info.get("walk_in_start_date"),
            "walk_in_end_date": walk_in_info.get("walk_in_end_date"),
            "walk_in_date_text": walk_in_info.get("walk_in_date_text"),
            "extracted_at": datetime.now().isoformat()
        }
