"""
Base Source Connector with RFC-compliant Robots.txt parsing, strict SSRF Protection,
Rate-limiting, Canonical URL normalization, and HTML sanitization.
"""

import os
import re
import time
import socket
import ipaddress
import logging
import hashlib
import urllib.request
import urllib.parse
import urllib.robotparser
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, Tuple, Set

logger = logging.getLogger("DigiGarment.SourceConnectors")

DEFAULT_USER_AGENT = "DigiGarmentBot/2.0 (+https://digigarment.com/bot; jobs-aggregator-bot)"
MAX_RESPONSE_BYTES = 5 * 1024 * 1024  # 5 MB max response limit
REQUEST_TIMEOUT = 10  # 10s per request

# Private and internal IP subnets to reject for SSRF Protection
DISALLOWED_IP_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]

class BaseSourceConnector(ABC):
    def __init__(
        self,
        source_id: str,
        source_name: str,
        base_url: str,
        allowed_domains: List[str],
        requests_per_minute: int = 20,
        user_agent: str = DEFAULT_USER_AGENT
    ):
        self.source_id = source_id
        self.source_name = source_name
        self.base_url = self.canonicalize_url(base_url)
        self.allowed_domains = [d.lower() for d in allowed_domains]
        self.min_request_interval = 60.0 / max(requests_per_minute, 1)
        self.user_agent = user_agent
        self.last_request_time = 0.0
        self._robot_parser: Optional[urllib.robotparser.RobotFileParser] = None
        self._robots_evaluated = False
        self._robots_allowed = True

    # -------------------------------------------------------------
    # 1. SSRF PROTECTION & DOMAIN VALIDATION
    # -------------------------------------------------------------
    def is_safe_url(self, url: str) -> Tuple[bool, str]:
        """
        Validates URL against SSRF attacks, private IP ranges, non-HTTP schemes,
        and ensures the target domain is on the approved allowlist.
        """
        try:
            parsed = urllib.parse.urlparse(url)
            scheme = (parsed.scheme or "").lower()
            if scheme not in ("http", "https"):
                return False, f"Disallowed URL scheme '{scheme}'. Only HTTP/HTTPS allowed."

            hostname = parsed.hostname
            if not hostname:
                return False, "Missing hostname in URL."

            host_lower = hostname.lower()
            if host_lower in ("localhost", "127.0.0.1", "0.0.0.0"):
                return False, "Localhost targets are strictly blocked."

            # Check domain allowlist
            domain_allowed = any(
                host_lower == d or host_lower.endswith(f".{d}")
                for d in self.allowed_domains
            )
            if not domain_allowed:
                return False, f"Domain '{host_lower}' is not in approved connector allowlist ({self.allowed_domains})."

            # Resolve DNS to verify IP is not in private/internal networks
            try:
                addr_info = socket.getaddrinfo(hostname, None)
                for item in addr_info:
                    ip_str = item[4][0]
                    ip_obj = ipaddress.ip_address(ip_str)
                    for net in DISALLOWED_IP_NETWORKS:
                        if ip_obj in net:
                            return False, f"Resolved IP '{ip_str}' is in private network '{net}' (SSRF Blocked)."
            except socket.gaierror as e:
                return False, f"DNS resolution failed for hostname '{hostname}': {e}"

            return True, "URL is safe"
        except Exception as e:
            return False, f"URL validation error: {e}"

    # -------------------------------------------------------------
    # 2. CANONICAL URL NORMALIZATION
    # -------------------------------------------------------------
    def canonicalize_url(self, url: str) -> str:
        """
        Normalizes URLs: strips tracking parameters (utm_*, fbclid, etc.),
        lowercases scheme and domain, strips fragments and duplicate slashes.
        """
        if not url:
            return ""
        parsed = urllib.parse.urlparse(url.strip())
        scheme = (parsed.scheme or "https").lower()
        netloc = (parsed.netloc or "").lower()
        path = parsed.path or "/"
        
        # Clean path duplicate slashes
        path = re.sub(r'/+', '/', path)
        if path == "/":
            path = ""
        elif path.endswith('/'):
            path = path[:-1]

        # Filter tracking query parameters
        tracking_keys = {
            "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
            "fbclid", "gclid", "ref", "source", "campaign", "fb_action_ids"
        }
        query_params = urllib.parse.parse_qsl(parsed.query, keep_blank_values=False)
        clean_params = [(k, v) for k, v in query_params if k.lower() not in tracking_keys]
        clean_params.sort(key=lambda x: x[0])
        clean_query = urllib.parse.urlencode(clean_params)

        return urllib.parse.urlunparse((scheme, netloc, path, "", clean_query, ""))

    # -------------------------------------------------------------
    # 3. ROBOTS.TXT COMPLIANCE
    # -------------------------------------------------------------
    def evaluate_robots(self) -> bool:
        """
        Fetches and evaluates the site's robots.txt policy RFC compliance.
        """
        if self._robots_evaluated:
            return self._robots_allowed

        robots_url = urllib.parse.urljoin(self.base_url, "/robots.txt")
        safe, msg = self.is_safe_url(robots_url)
        if not safe:
            logger.warning(f"Robots URL safety check failed for {self.source_name}: {msg}")
            self._robots_allowed = False
            self._robots_evaluated = True
            return False

        rp = urllib.robotparser.RobotFileParser()
        try:
            req = urllib.request.Request(
                robots_url,
                headers={"User-Agent": self.user_agent}
            )
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                if resp.status == 200:
                    content = resp.read(100000).decode("utf-8", errors="ignore")
                    rp.parse(content.splitlines())
                    logger.info(f"Loaded robots.txt for {self.source_name}")
                else:
                    rp.allow_all = True
        except urllib.error.HTTPError as e:
            if e.code in (404, 410):
                rp.allow_all = True
            else:
                logger.warning(f"robots.txt returned HTTP {e.code} for {self.source_name}; assuming allowed with throttling.")
                rp.allow_all = True
        except Exception as e:
            logger.warning(f"Could not fetch robots.txt for {self.source_name} ({e}); defaulting to permissive policy with rate limits.")
            rp.allow_all = True

        self._robot_parser = rp
        self._robots_allowed = True
        self._robots_evaluated = True
        return self._robots_allowed

    def can_fetch(self, url: str) -> bool:
        """
        Checks if the specific URL path is permitted under robots.txt.
        """
        if not self._robots_evaluated:
            self.evaluate_robots()
        if not self._robot_parser:
            return True
        return self._robot_parser.can_fetch(self.user_agent, url)

    # -------------------------------------------------------------
    # 4. RATE-LIMITED HTTP FETCHING
    # -------------------------------------------------------------
    def fetch_page(self, url: str, max_retries: int = 2) -> Tuple[Optional[str], Optional[int], Optional[str]]:
        """
        Fetches an HTML page safely with rate-limiting, exponential backoff,
        and max size limit. Returns (html_content, status_code, error_message).
        """
        canon_url = self.canonicalize_url(url)
        safe, reason = self.is_safe_url(canon_url)
        if not safe:
            return None, 400, f"SSRF Blocked: {reason}"

        if not self.can_fetch(canon_url):
            return None, 403, f"BLOCKED_BY_ROBOTS: URL disallowed by robots.txt"

        # Enforce rate limit delay
        elapsed = time.time() - self.last_request_time
        if elapsed < self.min_request_interval:
            time.sleep(self.min_request_interval - elapsed)

        headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,ta;q=0.8"
        }

        for attempt in range(max_retries + 1):
            try:
                self.last_request_time = time.time()
                req = urllib.request.Request(canon_url, headers=headers)
                with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                    status = resp.status
                    raw_bytes = resp.read(MAX_RESPONSE_BYTES)
                    content_type = resp.headers.get("Content-Type", "")
                    encoding = "utf-8"
                    if "charset=" in content_type:
                        encoding = content_type.split("charset=")[-1].split(";")[0].strip()
                    html_text = raw_bytes.decode(encoding, errors="ignore")
                    return html_text, status, None
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    if attempt < max_retries:
                        backoff = (2 ** attempt) * 3.0
                        logger.warning(f"Rate limited (429) for {canon_url}. Backing off {backoff:.1f}s...")
                        time.sleep(backoff)
                        continue
                    return None, 429, "HTTP 429 Too Many Requests (Rate Limited)"
                elif e.code == 403:
                    return None, 403, "HTTP 403 Forbidden (Access Denied / Anti-bot Protection)"
                elif e.code == 404:
                    return None, 404, "HTTP 404 Not Found"
                else:
                    return None, e.code, f"HTTP Error {e.code}: {e.reason}"
            except urllib.error.URLError as e:
                if attempt < max_retries:
                    time.sleep(1.5)
                    continue
                return None, 504, f"Network Error: {e.reason}"
            except Exception as e:
                return None, 500, f"Fetch Error: {e}"

        return None, 500, "Maximum retries exceeded"

    # -------------------------------------------------------------
    # 5. CONTENT & SOURCE HASHING
    # -------------------------------------------------------------
    def compute_content_hash(self, text: str) -> str:
        clean = re.sub(r'\s+', ' ', (text or "").strip().lower())
        return hashlib.sha256(clean.encode("utf-8")).hexdigest()

    def compute_source_hash(self, canonical_url: str) -> str:
        payload = f"{self.source_name}::{canonical_url.strip().lower()}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    # -------------------------------------------------------------
    # 6. HTML SANITIZATION & FACTUAL TEXT EXTRACTION
    # -------------------------------------------------------------
    def clean_html_to_text(self, html: str) -> str:
        """
        Removes scripts, styles, navigation, headers, footers, and extracts clean readable text.
        """
        if not html:
            return ""
        # Remove script and style tags
        text = re.sub(r'<script[^>]*>.*?</script>', ' ', html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<style[^>]*>.*?</style>', ' ', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<nav[^>]*>.*?</nav>', ' ', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<footer[^>]*>.*?</footer>', ' ', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<header[^>]*>.*?</header>', ' ', text, flags=re.DOTALL | re.IGNORECASE)
        # Convert block tags to newlines
        text = re.sub(r'<(?:div|p|h[1-6]|li|tr|br)[^>]*>', '\n', text, flags=re.IGNORECASE)
        # Strip all remaining tags
        text = re.sub(r'<[^>]+>', ' ', text)
        # Decode HTML entities
        import html as html_lib
        text = html_lib.unescape(text)
        # Collapse excessive whitespace
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return '\n'.join(lines)

    # -------------------------------------------------------------
    # 7. ABSTRACT CONNECTOR METHODS
    # -------------------------------------------------------------
    @abstractmethod
    def discover_job_urls(self, max_pages: int = 3) -> List[str]:
        """
        Discovers job URLs from public listing pages.
        """
        pass

    @abstractmethod
    def parse_job_page(self, url: str, html_content: str) -> Dict[str, Any]:
        """
        Parses a job page HTML into normalized raw source structure.
        """
        pass
