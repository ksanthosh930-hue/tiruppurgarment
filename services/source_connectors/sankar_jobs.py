"""
Sankar Jobs Website Connector (Step 3F.1).
Specialized connector for Sankar Jobs Garment Jobs Category (https://www.sankarjobs.com/category/4).
Implements dynamic pagination, strict last-10-day date filtering, Read More detail page extraction,
multi-vacancy segmentation, Source != Company separation, and robust noise sanitization.
"""

import re
import logging
import urllib.parse
from datetime import datetime, date, timedelta
from typing import List, Dict, Any, Optional, Tuple

from services.source_connectors.base import BaseSourceConnector
from services.normalizer import (
    normalize_company_name, normalize_location, normalize_phone_number
)

logger = logging.getLogger("DigiGarment.SankarJobsConnector")

class SankarJobsConnector(BaseSourceConnector):
    CATEGORY_PATH = "/category/4"
    DEFAULT_LOOKBACK_DAYS = 10

    def __init__(self, requests_per_minute: int = 20):
        super().__init__(
            source_id="sankar_jobs",
            source_name="Sankar Jobs",
            base_url="https://www.sankarjobs.com",
            allowed_domains=["sankarjobs.com", "www.sankarjobs.com"],
            requests_per_minute=requests_per_minute
        )

    def parse_sankar_date(self, date_str: str) -> Optional[date]:
        """
        Parses Sankar Jobs date string in formats:
        - DD/MM/YYYY (e.g. 01/09/2026)
        - DD-MM-YYYY
        - YYYY-MM-DD
        """
        if not date_str:
            return None
        date_clean = date_str.strip()
        
        # Match DD/MM/YYYY or DD-MM-YYYY
        m = re.search(r'\b(\d{1,2})[/\-\.](\d{1,2})[/\-\.](\d{4})\b', date_clean)
        if m:
            day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
            try:
                return date(year, month, day)
            except ValueError:
                pass
                
        # Match YYYY-MM-DD
        m_iso = re.search(r'\b(\d{4})-(\d{1,2})-(\d{1,2})\b', date_clean)
        if m_iso:
            year, month, day = int(m_iso.group(1)), int(m_iso.group(2)), int(m_iso.group(3))
            try:
                return date(year, month, day)
            except ValueError:
                pass

        return None

    def discover_job_urls(
        self,
        max_pages: int = 15,
        lookback_days: int = DEFAULT_LOOKBACK_DAYS,
        target_date: Optional[date] = None
    ) -> Dict[str, Any]:
        """
        Discovers individual Read More job URLs strictly within the last `lookback_days`
        from https://www.sankarjobs.com/category/4.
        
        Date Filter Logic:
        today = target_date or system date
        cutoff_date = today - lookback_days
        Qualifying condition: cutoff_date <= post_date <= today
        
        Pagination Stop Condition:
        If all posts on a page are older than cutoff_date, stop discovering further pages immediately.
        """
        today = target_date or datetime.now().date()
        cutoff_date = today - timedelta(days=lookback_days)
        
        discovered_posts: List[Dict[str, Any]] = []
        visited_pages = set()
        pages_visited_count = 0
        older_posts_skipped = 0
        total_listing_cards_found = 0
        
        current_page_url = urllib.parse.urljoin(self.base_url, self.CATEGORY_PATH)
        current_page_num = 1
        
        logger.info(f"Starting Sankar Jobs discovery from {current_page_url} | Lookback: {lookback_days} days (Cutoff: {cutoff_date} to {today})")

        while current_page_url and current_page_num <= max_pages:
            canon_page_url = self.canonicalize_url(current_page_url)
            if canon_page_url in visited_pages:
                break
            visited_pages.add(canon_page_url)
            pages_visited_count += 1

            html_content, status_code, fetch_err = self.fetch_page(canon_page_url)
            if not html_content or status_code != 200:
                logger.warning(f"Failed to fetch Sankar Jobs category page {canon_page_url} (HTTP {status_code}: {fetch_err})")
                break

            # Parse listing cards on this page
            cards_data, next_page_url = self._extract_listing_cards_and_pagination(html_content, canon_page_url, current_page_num)
            total_listing_cards_found += len(cards_data)
            
            if not cards_data:
                logger.info(f"No job cards found on page {current_page_num}. Ending pagination.")
                break

            page_dates = []
            page_qualifying_count = 0
            page_older_count = 0

            for card in cards_data:
                post_date = card.get("post_date")
                read_more_url = card.get("read_more_url")
                
                if not read_more_url:
                    continue

                if post_date:
                    page_dates.append(post_date)
                    if cutoff_date <= post_date <= today:
                        discovered_posts.append(card)
                        page_qualifying_count += 1
                    elif post_date < cutoff_date:
                        older_posts_skipped += 1
                        page_older_count += 1
                    else:
                        # Future date or anomaly: include safely if within reason
                        discovered_posts.append(card)
                        page_qualifying_count += 1
                else:
                    # Date not visible on card; follow to detail page to check date
                    discovered_posts.append(card)
                    page_qualifying_count += 1

            logger.info(
                f"Page {current_page_num}: {len(cards_data)} cards found "
                f"({page_qualifying_count} within {lookback_days}-day range, {page_older_count} older skipped). "
                f"Dates on page: {[d.isoformat() for d in set(page_dates)]}"
            )

            # --- PAGINATION STOP CONDITION ---
            # If all cards on this page have parsed dates and EVERY single post is older than cutoff_date,
            # then all subsequent pages will only have older posts. Stop crawling now!
            if page_dates and all(d < cutoff_date for d in page_dates):
                logger.info(
                    f"Stop condition reached on page {current_page_num}: All {len(page_dates)} posts on page "
                    f"are older than cutoff date {cutoff_date}. Halting pagination."
                )
                break

            # Advance to next page
            if next_page_url and next_page_url not in visited_pages:
                current_page_url = next_page_url
                current_page_num += 1
            else:
                # Fallback check for ?page=N+1
                fallback_next = f"{urllib.parse.urljoin(self.base_url, self.CATEGORY_PATH)}?page={current_page_num + 1}"
                if fallback_next not in visited_pages and current_page_num < max_pages:
                    current_page_url = fallback_next
                    current_page_num += 1
                else:
                    break

        return {
            "source_id": self.source_id,
            "source_name": self.source_name,
            "category_url": urllib.parse.urljoin(self.base_url, self.CATEGORY_PATH),
            "today": today.isoformat(),
            "cutoff_date": cutoff_date.isoformat(),
            "lookback_days": lookback_days,
            "pages_visited": pages_visited_count,
            "total_cards_discovered": total_listing_cards_found,
            "posts_within_lookback": len(discovered_posts),
            "older_posts_skipped": older_posts_skipped,
            "qualifying_posts": discovered_posts,
            "job_urls": [p["read_more_url"] for p in discovered_posts]
        }

    def _extract_listing_cards_and_pagination(
        self,
        html_content: str,
        current_url: str,
        current_page_num: int
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """
        Parses Sankar Jobs category HTML to extract post cards and the next pagination link.
        """
        cards_data: List[Dict[str, Any]] = []
        next_page_url: Optional[str] = None
        
        # Split cards by Read More anchors or card containers
        # On sankarjobs.com, each job card contains a Read More link like:
        # <a href="https://www.sankarjobs.com/jobs/garment-jobs-aviram-knitters-6640">Read More</a>
        # or relative href="/jobs/garment-jobs-..."
        
        # 1. Regex find all Read More link occurrences with their preceding card context
        # Pattern captures card block or lines surrounding the Read More link
        card_split_pattern = re.compile(
            r'(<div[^>]*class=[\'"][^\'"]*(?:card|job-item|col-)[^\'"]*[\'"][^>]*>[\s\S]*?<a[^>]+href=[\'"]([^\'"]+jobs/[^\'"]+)[\'"][^>]*>[\s\S]*?Read More[\s\S]*?</div>\s*</div>)',
            re.IGNORECASE
        )
        
        matches = card_split_pattern.findall(html_content)
        
        seen_urls = set()
        if matches:
            for block_html, href in matches:
                full_url = urllib.parse.urljoin(self.base_url, href)
                canon_url = self.canonicalize_url(full_url)
                if canon_url in seen_urls:
                    continue
                seen_urls.add(canon_url)
                
                card_info = self._parse_listing_card_block(block_html, canon_url)
                cards_data.append(card_info)
        else:
            # Fallback DOM parser if card class names differ
            link_pattern = re.compile(r'<a[^>]+href=[\'"]([^\'"]*(?:/jobs/)[^\'"]+)[\'"][^>]*>([\s\S]*?)</a>', re.IGNORECASE)
            for m in link_pattern.finditer(html_content):
                href = m.group(1).strip()
                link_text = re.sub(r'<[^>]+>', '', m.group(2)).strip()
                if "read more" in link_text.lower() or "view" in link_text.lower() or "details" in link_text.lower():
                    full_url = urllib.parse.urljoin(self.base_url, href)
                    canon_url = self.canonicalize_url(full_url)
                    if canon_url not in seen_urls:
                        seen_urls.add(canon_url)
                        # Extract surrounding 1000 characters of HTML around the match
                        start_pos = max(0, m.start() - 800)
                        end_pos = min(len(html_content), m.end() + 200)
                        block_snippet = html_content[start_pos:end_pos]
                        card_info = self._parse_listing_card_block(block_snippet, canon_url)
                        cards_data.append(card_info)

        # 2. Extract Next Page URL
        # Look for <a ...>Next</a> or <a href="...page=N+1">
        next_match = re.search(r'<a[^>]+href=[\'"]([^\'"]+[\?&]page=(\d+)[^\'"]*)[\'"][^>]*>\s*(?:Next|»|›|&gt;|>)\s*</a>', html_content, re.IGNORECASE)
        if next_match:
            next_href = next_match.group(1).replace("&amp;", "&")
            next_page_url = urllib.parse.urljoin(self.base_url, next_href)
        else:
            # Look for page number link for current_page_num + 1
            target_page_str = str(current_page_num + 1)
            num_match = re.search(r'<a[^>]+href=[\'"]([^\'"]+[\?&]page=' + target_page_str + r'[^\'"]*)[\'"][^>]*>\s*' + target_page_str + r'\s*</a>', html_content, re.IGNORECASE)
            if num_match:
                next_page_url = urllib.parse.urljoin(self.base_url, num_match.group(1).replace("&amp;", "&"))

        return cards_data, next_page_url

    def _parse_listing_card_block(self, block_html: str, read_more_url: str) -> Dict[str, Any]:
        """
        Extracts post date, company (if visible), location, and phone from a listing card block.
        """
        clean_text = self.clean_html_to_text(block_html)
        
        # 1. Post Date
        date_match = re.search(r'\b(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{4}|\d{4}-\d{2}-\d{2})\b', clean_text)
        post_date = self.parse_sankar_date(date_match.group(1)) if date_match else None
        
        # 2. Location
        card_location = None
        loc_match = re.search(r'(?:Tiruppur|Tirupur|Palladam|Avinashi|Dharapuram|Kangayam|Perumanallur|Veerapandi|Mangalam|Uthukuli|Pandian Nagar|PN Road|Boyampalayam|Kuppandampalayam|Nallur|Neruperichal)[^\n,]*', clean_text, re.IGNORECASE)
        if loc_match:
            card_location = normalize_location(loc_match.group(0))

        # 3. Company Name (if present on card, e.g. "AVIRAM KNITTERS")
        card_company = None
        lines = [l.strip() for l in clean_text.splitlines() if l.strip()]
        for line in lines:
            lower_l = line.lower()
            # Ignore non-company lines
            if any(k in lower_l for k in ["garment jobs", "share on whatsapp", "read more", "posted", "date", "call", "whatsapp"]):
                continue
            if re.search(r'\b\d{10}\b|\b\d{1,2}/\d{1,2}/\d{4}\b', line):
                continue
            if any(suffix in lower_l for suffix in ["garments", "knitters", "apparels", "apparel", "exports", "textiles", "knits", "clothing", "mills", "creations", "fashions", "pvt ltd"]):
                cand, _ = normalize_company_name(line)
                if cand and cand.lower() != "garment jobs":
                    card_company = cand
                    break

        # 4. Contact Phone
        card_phones = re.findall(r'\b[6-9]\d{9}\b', clean_text)
        primary_phone = normalize_phone_number(card_phones[0]) if card_phones else None

        return {
            "read_more_url": read_more_url,
            "post_date": post_date,
            "post_date_str": post_date.isoformat() if post_date else None,
            "card_company": card_company,
            "card_location": card_location,
            "card_phone": primary_phone,
            "card_raw_text": clean_text
        }

    def parse_job_page(
        self,
        url: str,
        html_content: str,
        card_meta: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Parses an individual Sankar Jobs Read More detail page into clean, structured raw source data.
        
        Strict Rules:
        - Source: Sankar Jobs does NOT mean Company = Sankar Jobs.
        - If company not mentioned -> company_name = None (NULL).
        - Extracts actual job designations and descriptions (NOT "Garment Jobs").
        - Filters out website navigation, social share buttons, advertisements, footer text.
        - Preserves embedded flyer poster image URL.
        """
        canon_url = self.canonicalize_url(url)
        card_meta = card_meta or {}

        # 1. Extract Main Job Container
        # Sankar Jobs puts the job detail inside <div class="job-detail"> or <div class="card-body">
        detail_container_match = re.search(
            r'<div[^>]*class=[\'"][^\'"]*(?:job-detail|card-body|job-content)[^\'"]*[\'"][^>]*>([\s\S]*?)(?:<footer|</body>|$)',
            html_content,
            re.IGNORECASE
        )
        container_html = detail_container_match.group(1) if detail_container_match else html_content

        # Clean HTML to text focused on job container
        clean_text = self.clean_html_to_text(container_html)
        
        # Remove noisy Sankar Jobs website widgets from clean text
        noise_patterns = [
            r'Navigation Menu[\s\S]*?Contact',
            r'Share on WhatsApp',
            r'Call Employer',
            r'WhatsApp',
            r'Back\s+Garment Jobs',
            r'Browse Jobs',
            r'Join our WhatsApp group[^\n]*',
            r'Join our Telegram group[^\n]*',
            r'Copyright[^\n]*Sankar Jobs[^\n]*',
            r'https?://[^\s]*sankarjobs\.com[^\s]*'
        ]
        sanitized_text = clean_text
        for np in noise_patterns:
            sanitized_text = re.sub(np, ' ', sanitized_text, flags=re.IGNORECASE)
            
        sanitized_lines = [l.strip() for l in sanitized_text.splitlines() if l.strip()]
        clean_job_text = '\n'.join(sanitized_lines)

        # 2. Extract Company Name (STRICT: Source != Company)
        # Sankar Jobs explicitly shows:
        # Company Details
        # Company
        # AVIRAM KNITTERS
        # Location
        # ...
        company_name = None
        
        # Check explicit "Company\n<Name>" in Company Details section
        comp_section_match = re.search(r'Company\s*Details[\s\S]*?Company\s*\n\s*([^\n]+)', clean_text, re.IGNORECASE)
        if comp_section_match:
            cand_comp = comp_section_match.group(1).strip()
            if cand_comp and not any(k in cand_comp.lower() for k in ["location", "contact", "details", "tiruppur", "road"]):
                clean_comp, _ = normalize_company_name(cand_comp)
                if clean_comp and clean_comp.lower() not in ["garment jobs", "direct employer", "sankar jobs"]:
                    company_name = clean_comp

        # Fallback to card company if found
        if not company_name and card_meta.get("card_company"):
            company_name = card_meta["card_company"]

        # Check in body text for explicit company mentions
        if not company_name:
            for line in sanitized_lines[-10:]:
                lower_l = line.lower()
                if any(suffix in lower_l for suffix in ["garments", "knitters", "apparels", "apparel", "exports", "textiles", "knits", "clothing", "mills", "creations", "fashions", "pvt ltd"]):
                    clean_l = re.sub(r'^(?:company|unit|factory|address|at)\s*[:=-]?\s*', '', line, flags=re.IGNORECASE).strip()
                    cand_comp, _ = normalize_company_name(clean_l)
                    if cand_comp and cand_comp.lower() not in ["garment jobs", "sankar jobs", "direct employer"]:
                        company_name = cand_comp
                        break

        # MANDATORY: If company is not mentioned, it MUST be None (NULL in DB). Do NOT invent employer.
        if company_name and company_name.lower() in ["garment jobs", "sankar jobs", "direct employer", "unknown employer", "garment manufacturer"]:
            company_name = None

        # 3. Extract Location
        # Check explicit "Location\n<Address>"
        location = None
        loc_section_match = re.search(r'Location\s*\n\s*([^\n]+)', clean_text, re.IGNORECASE)
        if loc_section_match:
            raw_loc = loc_section_match.group(1).strip()
            if raw_loc and not any(k in raw_loc.lower() for k in ["contact", "details", "call", "whatsapp"]):
                location = normalize_location(raw_loc)

        if not location and card_meta.get("card_location"):
            location = card_meta["card_location"]
            
        if not location:
            location = normalize_location(clean_job_text)

        # 4. Extract Contact Details
        # Sankar Jobs puts phone numbers in "Contact Details\n<Numbers>"
        contact_phones = []
        contact_section_match = re.search(r'Contact\s*Details\s*\n([\s\S]*?)(?:WhatsApp|Call Employer|Company Details|$)', clean_text, re.IGNORECASE)
        if contact_section_match:
            sec_text = contact_section_match.group(1)
            sec_phones = re.findall(r'\b[6-9]\d{9}\b', sec_text)
            for p in sec_phones:
                norm_p = normalize_phone_number(p)
                if norm_p and norm_p not in contact_phones:
                    contact_phones.append(norm_p)

        # Body phones scan across clean_text and clean_job_text
        all_raw_phones = re.findall(r'\b[6-9]\d{9}\b', clean_text)
        for p in all_raw_phones:
            norm_p = normalize_phone_number(p)
            if norm_p and norm_p not in contact_phones:
                contact_phones.append(norm_p)

        primary_phone = contact_phones[0] if contact_phones else card_meta.get("card_phone")
        secondary_phone = contact_phones[1] if len(contact_phones) > 1 else primary_phone

        # 5. Extract Posted Date
        posted_date_obj = None
        date_match = re.search(r'\b(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{4}|\d{4}-\d{2}-\d{2})\b', clean_text)
        if date_match:
            posted_date_obj = self.parse_sankar_date(date_match.group(1))
        if not posted_date_obj and card_meta.get("post_date"):
            posted_date_obj = card_meta["post_date"]

        posted_date_str = posted_date_obj.isoformat() if posted_date_obj else datetime.now().date().isoformat()

        # 6. Extract Embedded Flyer / Poster Image
        # Sankar Jobs embeds flyer image at e.g. https://www.sankarjobs.com/jobs/1788227425.png
        image_url = None
        img_matches = re.findall(r'<img[^>]+src=[\'"]([^\'"]+?)[\'"]', html_content, re.IGNORECASE)
        for img in img_matches:
            img_lower = img.lower()
            if any(ext in img_lower for ext in [".jpg", ".jpeg", ".png", ".webp"]):
                # Skip Sankar Jobs logos, icons, banners, whatsapp icons
                if not any(skip in img_lower for skip in ["logo", "icon", "banner", "avatar", "analytics", "whatsapp", "facebook", "twitter"]):
                    # Legitimate job poster image
                    image_url = urllib.parse.urljoin(canon_url, img)
                    break

        # 7. Extract Title & Reference Slug
        path_slug = urllib.parse.urlparse(canon_url).path.strip("/").split("/")[-1]
        source_reference = path_slug if path_slug else f"sankar_{self.compute_content_hash(clean_job_text)[:12]}"
        
        # Do NOT treat "Garment Jobs" as job designation
        # Clean title from H1 or slug
        title = "Garment Job Vacancy"
        h1_match = re.search(r'<h1[^>]*>(.*?)</h1>', html_content, re.IGNORECASE | re.DOTALL)
        if h1_match:
            h1_clean = re.sub(r'<[^>]+>', '', h1_match.group(1)).strip()
            if len(h1_clean) >= 4 and h1_clean.lower() != "garment jobs":
                title = h1_clean

        # 8. Compute Hashes
        content_hash = self.compute_content_hash(clean_job_text)
        source_hash = self.compute_source_hash(canon_url)

        return {
            "source_type": "website",
            "source_name": "Sankar Jobs",
            "source_url": canon_url,
            "source_reference": source_reference,
            "source_posted_date": posted_date_str,
            "source_posted_at": posted_date_str,
            "title": title,
            "company_name": company_name,
            "location": location,
            "contact_phone": primary_phone,
            "contact_whatsapp": secondary_phone or primary_phone,
            "contact_email": None,
            "raw_text": clean_job_text,
            "image_url": image_url,
            "content_hash": content_hash,
            "source_hash": source_hash,
            "metadata": {
                "domain": "sankarjobs.com",
                "category": "Garment Jobs (Category 4)",
                "parsed_at": datetime.now().isoformat(),
                "has_poster_image": bool(image_url),
                "is_employer_mentioned": bool(company_name)
            }
        }
