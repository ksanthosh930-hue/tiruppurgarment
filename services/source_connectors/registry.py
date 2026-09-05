"""
Source Connector Registry and Ingestion Coordinator for DigiGarment Website Connectors.
"""

import time
import json
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional, Type

from services.source_connectors.base import BaseSourceConnector
from services.source_connectors.sankar_jobs import SankarJobsConnector
from services.source_connectors.cotton_jobs import CottonJobsConnector
from services.extractor import StructuredJobExtractor
from services.company_matcher import CompanyMatcher
from services.deduplicator import JobDeduplicator

logger = logging.getLogger("DigiGarment.ConnectorRegistry")

def import_json_dumps(val: Any) -> str:
    return json.dumps(val, default=str)

class ConnectorRegistry:
    def __init__(self):
        self._connectors: Dict[str, BaseSourceConnector] = {}
        self._extractor = StructuredJobExtractor()
        self._register_default_connectors()

    def _register_default_connectors(self):
        self.register(SankarJobsConnector())
        self.register(CottonJobsConnector())

    def register(self, connector: BaseSourceConnector):
        self._connectors[connector.source_id] = connector
        logger.info(f"Registered website source connector: {connector.source_id} ({connector.source_name})")

    def get_connector(self, source_id: str) -> Optional[BaseSourceConnector]:
        return self._connectors.get(source_id)

    def list_connectors(self) -> List[Dict[str, Any]]:
        return [
            {
                "source_id": c.source_id,
                "source_name": c.source_name,
                "base_url": c.base_url,
                "allowed_domains": c.allowed_domains
            }
            for c in self._connectors.values()
        ]

    def run_connector(
        self,
        source_id: str,
        max_pages: int = 10,
        lookback_days: int = 10,
        db_query_fn=None,
        db_exec_fn=None,
        db_exec_ret_fn=None
    ) -> Dict[str, Any]:
        """
        Executes a crawl run for a specific connector:
        1. Evaluates robots.txt policy
        2. Discovers public job URLs with strict lookback_days date filtering
        3. Stops pagination immediately when posts exceed lookback cutoff
        4. Fetches and parses detail pages safely (Source != Company separation)
        5. Identifies exact duplicates / content changes via source_url and content_hash
        6. Runs multi-vacancy extraction engine
        7. Evaluates 4-tier deduplication against active master jobs
        8. Stages in raw_job_ingestions with PENDING_REVIEW status (Auto-publish DISABLED)
        9. Records crawl metrics in crawl_run_logs and website_sources
        """
        connector = self.get_connector(source_id)
        if not connector:
            raise ValueError(f"Unknown source connector '{source_id}'")

        start_time = time.time()
        start_ts = datetime.now()
        
        summary = {
            "source_id": source_id,
            "source_name": connector.source_name,
            "started_at": start_ts.isoformat(),
            "completed_at": None,
            "duration_seconds": 0.0,
            "robots_status": "PASS",
            "lookback_days": lookback_days,
            "pages_visited": 0,
            "job_urls_discovered": 0,
            "posts_within_lookback": 0,
            "older_posts_skipped": 0,
            "new_imported": 0,
            "exact_duplicates": 0,
            "possible_duplicates": 0,
            "content_changed_count": 0,
            "pending_review_count": 0,
            "extraction_successes": 0,
            "extraction_failures": 0,
            "ai_calls": 0,
            "local_parser_calls": 0,
            "paid_ai_cost": "₹0.00",
            "errors_count": 0,
            "status": "COMPLETED",
            "error_details": None,
            "imported_ingestion_ids": []
        }

        # 1. Evaluate Robots Policy
        try:
            robots_allowed = connector.evaluate_robots()
            if not robots_allowed:
                summary["robots_status"] = "BLOCKED_BY_ROBOTS"
                summary["status"] = "BLOCKED"
                summary["error_details"] = "Crawl blocked by site robots.txt policy."
                self._record_run_log(summary, db_exec_fn)
                return summary
        except Exception as e:
            logger.warning(f"Robots evaluation warning for {source_id}: {e}")
            summary["robots_status"] = "NEEDS_REVIEW"

        # 2. Discover Job URLs with Date Filter
        qualifying_posts: List[Dict[str, Any]] = []
        try:
            discovery_res = connector.discover_job_urls(max_pages=max_pages, lookback_days=lookback_days)
            if isinstance(discovery_res, dict):
                summary["pages_visited"] = discovery_res.get("pages_visited", 0)
                summary["job_urls_discovered"] = discovery_res.get("total_cards_discovered", 0)
                summary["posts_within_lookback"] = discovery_res.get("posts_within_lookback", 0)
                summary["older_posts_skipped"] = discovery_res.get("older_posts_skipped", 0)
                qualifying_posts = discovery_res.get("qualifying_posts", [])
            elif isinstance(discovery_res, list):
                summary["job_urls_discovered"] = len(discovery_res)
                summary["posts_within_lookback"] = len(discovery_res)
                summary["pages_visited"] = min(len(discovery_res) + 1, max_pages)
                qualifying_posts = [{"read_more_url": u} for u in discovery_res]
        except Exception as e:
            logger.error(f"Error during URL discovery for {source_id}: {e}")
            summary["errors_count"] += 1
            summary["error_details"] = f"URL discovery failed: {e}"

        # 3. Fetch Companies & Active Jobs for Matching and Deduplication
        existing_companies = []
        active_jobs = []
        if db_query_fn:
            try:
                existing_companies = db_query_fn("SELECT id, name, contact_phone, contact_email FROM companies WHERE status != 'INACTIVE';") or []
                active_jobs = db_query_fn("SELECT id, title, department, job_role, company_id, location, contact_phone, contact_whatsapp, description, content_hash, source_hash FROM jobs WHERE is_archived = FALSE AND status = 'published';") or []
            except Exception as dberr:
                logger.warning(f"Could not load companies/jobs for matching: {dberr}")

        comp_matcher = CompanyMatcher(existing_companies) if existing_companies else None
        deduplicator = JobDeduplicator(active_jobs) if active_jobs else None

        # 4. Process Each Qualifying Job Post
        for post_item in qualifying_posts:
            job_url = post_item.get("read_more_url")
            if not job_url:
                continue

            try:
                # Check repeat crawl in DB
                existing_ingestions = None
                if db_query_fn:
                    existing_ingestions = db_query_fn(
                        "SELECT id, content_hash, status FROM raw_job_ingestions WHERE source_url = %s AND parent_ingestion_id IS NULL LIMIT 1;",
                        (job_url,)
                    )

                html_content, status_code, fetch_err = connector.fetch_page(job_url)
                if not html_content or status_code != 200:
                    summary["errors_count"] += 1
                    continue

                raw_source = connector.parse_job_page(job_url, html_content, card_meta=post_item)
                content_hash = raw_source["content_hash"]

                # Repeat Crawl & Source Update Handling
                if existing_ingestions:
                    old_rec = existing_ingestions[0]
                    if old_rec.get("content_hash") == content_hash:
                        # Exact identical content already imported
                        summary["exact_duplicates"] += 1
                        continue
                    else:
                        # Content has changed on the source page!
                        summary["content_changed_count"] += 1
                        logger.info(f"CONTENT_CHANGED detected for {job_url}. Updating raw source ingestion.")

                # 5. Multi-Vacancy Extraction
                summary["local_parser_calls"] += 1
                extraction_res = self._extractor.process_multi_job_ingestion(
                    raw_text=raw_source["raw_text"]
                )

                vacancies = extraction_res.get("vacancies", [])
                if not vacancies:
                    vacancies = [extraction_res.get("primary_vacancy", {})]

                if vacancies:
                    summary["extraction_successes"] += 1
                else:
                    summary["extraction_failures"] += 1

                # 6. Entity Matching & Deduplication
                # Respect connector's extracted company name (Source != Company)
                extracted_comp = raw_source.get("company_name")
                matched_comp_id = None
                if extracted_comp and comp_matcher:
                    matched_comp, _, _ = comp_matcher.match_company(
                        extracted_comp,
                        phone=raw_source.get("contact_phone"),
                        email=raw_source.get("contact_email")
                    )
                    matched_comp_id = matched_comp["id"] if matched_comp else None

                # Process deduplication per vacancy
                processed_vacs = []
                for v in vacancies:
                    # Explicitly override company_name if extracted from detail page
                    if extracted_comp:
                        v["company_name"] = extracted_comp
                    elif not v.get("company_name") or v.get("company_name") in ["Direct Employer", "Garment Jobs"]:
                        v["company_name"] = None  # Employer Not Mentioned

                    v["matched_company_id"] = matched_comp_id
                    v["source_url"] = raw_source["source_url"]
                    v["source_posted_date"] = raw_source["source_posted_date"]

                    if deduplicator:
                        m_job, d_score, d_reasons, d_band = deduplicator.check_duplicate(
                            extracted_data=v,
                            content_hash=content_hash,
                            media_hash=raw_source.get("source_hash")
                        )
                        v["duplicate_score"] = d_score
                        v["duplicate_reasons"] = d_reasons
                        v["duplicate_status"] = d_band
                        v["matched_job_id"] = m_job["id"] if m_job else None
                        if d_score >= 0.70:
                            summary["possible_duplicates"] += 1
                    else:
                        v["duplicate_score"] = 0.0
                        v["duplicate_reasons"] = []
                        v["duplicate_status"] = "NEW"
                        v["matched_job_id"] = None

                    processed_vacs.append(v)

                total_vacs = len(processed_vacs)
                primary_vac = processed_vacs[0] if processed_vacs else {}

                # 7. Staging into Database with PENDING_REVIEW (NEVER AUTO-PUBLISH)
                if db_exec_ret_fn:
                    parent_rows = db_exec_ret_fn("""
                        INSERT INTO raw_job_ingestions (
                            source_type, source_name, source_url, source_reference, source_posted_date,
                            raw_text, raw_image_path, content_hash, status, extracted_data, confidence_score,
                            duplicate_score, matched_job_id, matched_company_id, duplicate_reasons,
                            total_vacancies, vacancy_index, ai_used, ai_skipped, created_at, updated_at
                        ) VALUES (
                            %s, %s, %s, %s, %s,
                            %s, %s, %s, 'PENDING_REVIEW', %s, %s,
                            %s, %s, %s, %s,
                            %s, 1, FALSE, TRUE, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                        ) RETURNING id;
                    """, (
                        raw_source["source_type"],
                        raw_source["source_name"],
                        raw_source["source_url"],
                        raw_source["source_reference"],
                        raw_source["source_posted_date"],
                        raw_source["raw_text"],
                        raw_source.get("poster_image_url") or raw_source.get("image_url"),
                        content_hash,
                        import_json_dumps(primary_vac),
                        primary_vac.get("confidence_score", 0.90),
                        primary_vac.get("duplicate_score", 0.0),
                        primary_vac.get("matched_job_id"),
                        matched_comp_id,
                        import_json_dumps(primary_vac.get("duplicate_reasons", [])),
                        total_vacs
                    ))

                    if parent_rows:
                        p_id = parent_rows[0]["id"]
                        summary["new_imported"] += 1
                        summary["pending_review_count"] += total_vacs
                        summary["imported_ingestion_ids"].append(p_id)

                        # Insert sub-vacancies (2..N)
                        if total_vacs > 1 and db_exec_fn:
                            for idx in range(1, total_vacs):
                                sub_vac = processed_vacs[idx]
                                db_exec_fn("""
                                    INSERT INTO raw_job_ingestions (
                                        parent_ingestion_id, vacancy_index, total_vacancies,
                                        source_type, source_name, source_url, source_reference, source_posted_date,
                                        raw_text, raw_image_path, content_hash, status, extracted_data, confidence_score,
                                        duplicate_score, matched_job_id, matched_company_id, duplicate_reasons,
                                        ai_used, ai_skipped, created_at, updated_at
                                    ) VALUES (
                                        %s, %s, %s,
                                        %s, %s, %s, %s, %s,
                                        %s, %s, %s, 'PENDING_REVIEW', %s, %s,
                                        %s, %s, %s, %s,
                                        FALSE, TRUE, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                                    );
                                """, (
                                    p_id, idx + 1, total_vacs,
                                    raw_source["source_type"],
                                    raw_source["source_name"],
                                    raw_source["source_url"],
                                    raw_source["source_reference"],
                                    raw_source["source_posted_date"],
                                    raw_source["raw_text"],
                                    raw_source.get("poster_image_url") or raw_source.get("image_url"),
                                    content_hash,
                                    import_json_dumps(sub_vac),
                                    sub_vac.get("confidence_score", 0.90),
                                    sub_vac.get("duplicate_score", 0.0),
                                    sub_vac.get("matched_job_id"),
                                    matched_comp_id,
                                    import_json_dumps(sub_vac.get("duplicate_reasons", []))
                                ))
                else:
                    # Offline simulated run
                    summary["new_imported"] += 1
                    summary["pending_review_count"] += total_vacs

            except Exception as item_err:
                logger.error(f"Error processing page {job_url}: {item_err}", exc_info=True)
                summary["errors_count"] += 1

        summary["duration_seconds"] = round(time.time() - start_time, 2)
        summary["completed_at"] = datetime.now().isoformat()

        # 8. Update Source Health & Run Log
        self._record_run_log(summary, db_exec_fn)
        return summary

    def _record_run_log(self, summary: Dict[str, Any], db_exec_fn):
        if not db_exec_fn:
            return
        try:
            # Update website_sources table
            db_exec_fn("""
                UPDATE website_sources 
                SET last_crawled_at = CURRENT_TIMESTAMP,
                    last_success_at = CASE WHEN %s = 'COMPLETED' THEN CURRENT_TIMESTAMP ELSE last_success_at END,
                    last_error_at = CASE WHEN %s != 'COMPLETED' OR %s > 0 THEN CURRENT_TIMESTAMP ELSE last_error_at END,
                    last_error_message = %s,
                    total_discovered = total_discovered + %s,
                    total_imported = total_imported + %s,
                    total_duplicates = total_duplicates + %s,
                    total_errors = total_errors + %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE source_id = %s;
            """, (
                summary["status"],
                summary["status"],
                summary["errors_count"],
                summary["error_details"],
                summary["job_urls_discovered"],
                summary["new_imported"],
                summary["exact_duplicates"],
                summary["errors_count"],
                summary["source_id"]
            ))

            # Insert into crawl_run_logs
            db_exec_fn("""
                INSERT INTO crawl_run_logs (
                    source_id, started_at, completed_at, duration_seconds, pages_visited,
                    job_urls_discovered, new_imported, exact_duplicates, possible_duplicates,
                    extraction_successes, extraction_failures, errors_count, status,
                    log_summary, error_details
                ) VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s
                );
            """, (
                summary["source_id"],
                summary["started_at"],
                summary["completed_at"],
                summary["duration_seconds"],
                summary["pages_visited"],
                summary["job_urls_discovered"],
                summary["new_imported"],
                summary["exact_duplicates"],
                summary["possible_duplicates"],
                summary["extraction_successes"],
                summary["extraction_failures"],
                summary["errors_count"],
                summary["status"],
                import_json_dumps(summary),
                summary["error_details"]
            ))
        except Exception as e:
            logger.error(f"Failed to record crawl run log for {summary.get('source_id')}: {e}")

# Singleton Registry Instance
connector_registry = ConnectorRegistry()
