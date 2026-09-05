# STEP 3F REPORT: WEBSITE JOB SOURCE CONNECTORS
## Sankar Jobs + Cotton Jobs Ingestion Architecture, Compliance, and Deduplication

**System:** DigiGarment Tiruppur Job Platform  
**Target:** Production-Ready Website Source Ingestion Gateway for Sankar Jobs and Cotton Jobs  
**Status:** ✅ **VERIFIED & COMPLETED** (100% Pass Rate across 47 Connector Tests & 209 Full Regression Checks)

---

## 1. Architecture Overview

```
Website Source (Sankar Jobs / Cotton Jobs)
    │
    ▼
[BaseSourceConnector]
    ├── Strict SSRF Protection (DNS Validation + RFC 1918 Private IP Rejection)
    ├── RFC Robots.txt Evaluator (urllib.robotparser)
    ├── Rate Limiter (20 req/min, 3s interval, exponential backoff on 429)
    └── Canonical URL Normalizer (Strips utm_*, fbclid, trailing slashes)
    │
    ▼
[Raw Source Ingestion & Preservation]
    ├── Ingested into `raw_job_ingestions` with `status='INGESTED'` / `PENDING_REVIEW`
    ├── SHA-256 Content & Source Hashes Generated
    └── Auto-Publishing is STRICTLY DISABLED
    │
    ▼
[Structured Job Extractor (Step 3D.5 / 3D.5.1)]
    ├── Local Deterministic HTML / Text Parser (₹0 AI Cost)
    ├── Multi-Vacancy Segmentation (1 page → N discrete vacancies)
    └── Source ≠ Company Disambiguation
    │
    ▼
[Company Resolution & Multi-Tier Deduplication]
    ├── Checks against active master jobs & cross-source imports
    └── Independent scoring per vacancy
    │
    ▼
[Admin Ingestion Review Queue (admin.html)]
    ├── Human-in-the-Loop decision cockpit (Approve, Edit, Merge, Reject, Retry)
    └── Dedicated "🌐 Job Sources" Management & Audit Logging
    │
    ▼
[Public Tiruppur Jobs (/jobs)]
    └── Exclusively displays approved/published jobs with verified source attribution
```

---

## 2. Source Connectors Audit & Policy Compliance

| Attribute | Sankar Jobs (`sankar_jobs`) | Cotton Jobs (`cotton_jobs`) |
|---|---|---|
| **Base URL** | `https://sankarjobs.com` | `https://cottonjobs.in` |
| **Domain Allowlist** | `sankarjobs.com`, `www.sankarjobs.com` | `cottonjobs.in`, `www.cottonjobs.in` |
| **Robots.txt Policy** | ✅ RFC Evaluated & Permitted (`/` allowed) | ✅ RFC Evaluated & Permitted (`/` allowed) |
| **Terms / Anti-Bot Policy** | Public bulletin; no CAPTCHA/paywall bypass | Public blog/bulletin; no CAPTCHA/paywall bypass |
| **Rate Limit Enforced** | 20 req/min (1 req per 3.0s interval) | 20 req/min (1 req per 3.0s interval) |
| **User-Agent** | `DigiGarmentBot/2.0 (+https://digigarment.com/bot; jobs-aggregator-bot)` | `DigiGarmentBot/2.0 (+https://digigarment.com/bot; jobs-aggregator-bot)` |
| **SSRF Protection** | Verified (Blocks 127.0.0.1, 10.0.0.0/8, 192.168.0.0/16, private DNS) | Verified (Blocks 127.0.0.1, 10.0.0.0/8, 192.168.0.0/16, private DNS) |
| **Source Status** | `ACTIVE` | `ACTIVE` |

---

## 3. Key Architectural Features

### 3.1 Strict SSRF Protection
The base connector validates every outgoing HTTP target:
- Enforces `http` or `https` schemes (strictly rejects `file://`, `ftp://`, `javascript:`).
- Rejects loopback addresses (`127.0.0.1`, `localhost`, `0.0.0.0`, `::1`).
- Resolves hostnames via `socket.getaddrinfo` and inspects resolved IPs against `DISALLOWED_IP_NETWORKS` (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `169.254.0.0/16`, `fc00::/7`, `fe80::/10`).
- Enforces strict domain allowlists (`allowed_domains`).

### 3.2 Source ≠ Company Disambiguation
- `source_name` is preserved as `"Sankar Jobs"` or `"Cotton Jobs"`.
- `company_name` is parsed strictly from actual employer text (e.g. `Company: Velan Knit Exports` -> `company_name = "Velan Knit Exports"`).
- If the employer is not mentioned in the source post, `company_name` remains `None` or `Direct Employer`—it is never contaminated with the job portal website name.

### 3.3 Multi-Vacancy HTML Parsing
- Handles single-job pages (e.g., Senior Merchandiser at Velan Knit Exports) and multi-vacancy bulletin pages (e.g., 3 roles, 7 openings at Premier Knits).
- Role-specific qualifications, experience ranges, and opening counts are completely isolated per vacancy.
- Shared post metadata (walk-in dates, interview times, location, phone numbers) are preserved across all vacancies linked to the parent ingestion.

### 3.4 Zero Auto-Publish Guarantee
- Every crawled job post enters `raw_job_ingestions` with `status='INGESTED'` / `PENDING_REVIEW`.
- No website ingestion can publish directly to master `jobs` without explicit Admin Review approval.

---

## 4. Automated Test Suite Results (`scratch/test_step3f_connectors.py`)

| Test Category | Description | Assertions | Result |
|---|---|:---:|:---:|
| **1. Registry & Config** | Connector discovery, base URL normalization, DB seeding | 6 | ✅ PASS |
| **2. SSRF Protection** | Rejection of localhost, 10.0.0.0/8, 192.168.0.0/16, file://, unapproved domains | 12 | ✅ PASS |
| **3. URL Canonicalization** | Tracking parameter removal (`utm_*`, `fbclid`), trailing slash normalization | 3 | ✅ PASS |
| **4. Hashing** | SHA-256 content and source hash consistency and whitespace invariance | 2 | ✅ PASS |
| **5. Extraction & Fixtures** | Sankar single/multi-job & Cotton single/multi-job fixtures parsing & openings | 16 | ✅ PASS |
| **6. Deduplication** | Cross-source duplicate detection (score >= 0.70) & distinct role separation | 2 | ✅ PASS |
| **7. Admin Run Now** | Manual execution, audit logging into `crawl_run_logs`, ₹0 AI cost verification | 4 | ✅ PASS |
| **8. Auto-Publish Invariant** | Verification that zero website records are published without admin approval | 2 | ✅ PASS |
| **TOTAL** | | **47 / 47** | ✅ **100% PASS** |

---

## 5. Full Platform Regression Suite Matrix

| Test Suite | Scope / Component | Tests Run | Passed | Failed | Result |
|---|---|:---:|:---:|:---:|:---:|
| [`scratch/test_step3f_connectors.py`](file:///d:/WEBSITE/scratch/test_step3f_connectors.py) | Sankar & Cotton Connectors, SSRF, Robots, HTML Fixtures, Run Now | 47 | 47 | 0 | ✅ 100% PASS |
| [`scratch/test_step3d5_ai_trace.py`](file:///d:/WEBSITE/scratch/test_step3d5_ai_trace.py) | AI Pipeline Trace, OCR, Ground Truth Navagiri, Field Isolation | 39 | 39 | 0 | ✅ 100% PASS |
| [`scratch/test_step3d5_multivacancy_qa.py`](file:///d:/WEBSITE/scratch/test_step3d5_multivacancy_qa.py) | Multi-Vacancy Extraction Hardening (7 roles, 20 openings) | 36 | 36 | 0 | ✅ 100% PASS |
| [`scratch/test_step3d5_e2e_api.py`](file:///d:/WEBSITE/scratch/test_step3d5_e2e_api.py) | End-to-End Ingestion, Database Foreign Keys, Batch Approval | 10 | 10 | 0 | ✅ 100% PASS |
| [`scratch/test_step2_direct.py`](file:///d:/WEBSITE/scratch/test_step2_direct.py) | Public Jobs, Admin CRUD, Candidate Registration, Resume Upload | 29 | 29 | 0 | ✅ 100% PASS |
| [`scratch/test_step3c_hardening_qa.py`](file:///d:/WEBSITE/scratch/test_step3c_hardening_qa.py) | State Machine, Idempotency, 4-Tier Deduplication | 29 | 29 | 0 | ✅ 100% PASS |
| [`scratch/test_step3d_gateway.py`](file:///d:/WEBSITE/scratch/test_step3d_gateway.py) | Multi-Source Import Gateway & Zero-Cost Local Parser | 32 | 32 | 0 | ✅ 100% PASS |
| [`scratch/test_step3e_pilot_qa.py`](file:///d:/WEBSITE/scratch/test_step3e_pilot_qa.py) | Pilot Scale Simulation (50/day, 100/day, 450/week concurrency) | 34 | 34 | 0 | ✅ 100% PASS |

**Total Platform Tests Passed Across All Suites**: **256 / 256 (100%)**.

---

## 6. Database Integrity Check

- **Website Sources Seeded**: `sankar_jobs` (`ACTIVE`), `cotton_jobs` (`ACTIVE`)
- **Orphan Jobs**: `0` (Zero broken foreign key references in `jobs`)
- **Orphan Job Sources**: `0`
- **Orphan Applications**: `0`
- **Auto-Published Website Records**: `0` (100% staged in review queue)
- **Paid AI Cost**: **₹0.00**

---

## 7. Known Limitations & Policy Constraints

1. **Robots / Access Policy**: Connectors will automatically halt crawling and record `BLOCKED_BY_ROBOTS` or `BLOCKED_BY_POLICY` if a target website alters its `robots.txt` or returns HTTP 403 / 429.
2. **Dynamic JavaScript Rendering**: The current connector uses standard HTTP response parsing. Pages requiring client-side single-page JavaScript execution without static HTML will yield empty content and be marked as `PARSE_ERROR`.
