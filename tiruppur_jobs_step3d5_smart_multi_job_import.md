# STEP 3D.5 — AI SMART MULTI-JOB IMPORT GATEWAY
## Architectural Specification, Implementation Audit & High-Volume Benchmark Report

**Document ID:** `tiruppur_jobs_step3d5_smart_multi_job_import.md`  
**System Module:** DigiGarment Tiruppur Jobs — Multi-Source Ingestion & Smart Multi-Job Gateway  
**Date:** August 27, 2026  
**Status:** COMPLETED & APPROVED (`PASS — READY FOR STEP 3F`)  

---

## 1. Executive Summary

DigiGarment's ingestion gateway has been upgraded to **Step 3D.5 — AI Smart Multi-Job Import Gateway**. 
Real-world Tiruppur job vacancy posts (particularly from WhatsApp channels, recruiter broadcasts, and factory flyers) commonly group multiple distinct job openings into a single message (e.g. *Training Manager (Sewing)*, *IT Assistant*, *Fabric DEO*, and *Costing Executive*). 

Under Step 3D.5, the ingestion gateway analyzes the entire announcement, detects all distinct job vacancies contained within, extracts role-specific attributes (salary, experience, requirements), links shared provenance metadata (poster image, company name, location, contact numbers), runs deduplication guardrails per individual job, and presents an interactive **Analysis Result Cockpit** in the Admin UI with single-click **Approve All & Publish** capabilities.

The zero-cost local-first architecture ensures that pure text announcements are parsed deterministically with **₹0 paid AI cost**.

---

## 2. Multi-Job Ingestion Architecture & Data Flow

```text
+-------------------------------------------------------------------------+
|                  EXTERNAL JOB SOURCE (WhatsApp Channel)                 |
|             "ABC Garments requires: Training Manager (Sewing),          |
|              IT Assistant, Fabric DEO, Costing Executive"               |
+-------------------------------------------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
|                 STEP 3D.5 SMART MULTI-JOB IMPORT GATEWAY                |
|                    POST /api/admin/ingestion/import                     |
+-------------------------------------------------------------------------+
                                     |
           +-------------------------+-------------------------+
           |                                                   |
           v                                                   v
+-----------------------+                           +---------------------+
| Local Deterministic   |                           | Free Vision AI Tier |
| Multi-Job Parser      |  (If poster image only)   | (Gemini 2.5 Flash)  |
| (Zero Paid AI Cost)   | ------------------------> | (Fallback Provider) |
+-----------------------+                           +---------------------+
           |                                                   |
           +-------------------------+-------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
|                       MULTI-JOB SEGMENTATION                            |
|             Dissects Announcement into N Distinct Vacancies             |
|   Inherits: Company, Location, Contact, Poster Image, Provenance        |
|   Extracts: Specific Role, Specific Department, Salary & Experience     |
+-------------------------------------------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
|                   DATABASE STAGING (Migration 004)                      |
|  raw_job_ingestions:                                                    |
|    - Record 1: parent_ingestion_id=NULL, vacancy_index=1, total=4       |
|    - Record 2: parent_ingestion_id=1,    vacancy_index=2, total=4       |
|    - Record 3: parent_ingestion_id=1,    vacancy_index=3, total=4       |
|    - Record 4: parent_ingestion_id=1,    vacancy_index=4, total=4       |
+-------------------------------------------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
|                     INDIVIDUAL JOB DEDUPLICATION                        |
|  - Deduplication evaluated per vacancy against active Master Jobs       |
|  - Role Guardrail: Role similarity < 0.65 strictly prevents merging     |
+-------------------------------------------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
|                       ADMIN COCKPIT REVIEW UI                           |
|  - 🧠 Analysis Result Grid: Job 1, Job 2, Job 3, Job 4 Cards           |
|  - Real-time confidence, duplicate status, and edit controls            |
|  - Actions: [ Approve All & Publish ] [ Review Individually ]           |
+-------------------------------------------------------------------------+
                                     |
           +-------------------------+-------------------------+
           |                                                   |
           v                                                   v
+-----------------------+                           +---------------------+
| Master Job Creation   |                           | Secondary Source    |
| (4 Distinct Records   |                           | Merging             |
|  in `jobs` table)     |                           | (`job_sources`)     |
+-----------------------+                           +---------------------+
```

---

## 3. Database Schema & Migration 004

To represent multi-job post hierarchies without duplicating large image blobs or corrupting historical provenance, Migration `004_smart_multi_job_import.sql` was applied to Supabase PostgreSQL:

```sql
-- Migration 004: Add multi-job support to raw_job_ingestions
ALTER TABLE raw_job_ingestions
ADD COLUMN IF NOT EXISTS parent_ingestion_id BIGINT REFERENCES raw_job_ingestions(id) ON DELETE SET NULL,
ADD COLUMN IF NOT EXISTS vacancy_index INTEGER DEFAULT 1,
ADD COLUMN IF NOT EXISTS total_vacancies INTEGER DEFAULT 1;

CREATE INDEX IF NOT EXISTS idx_raw_ingestions_parent_id ON raw_job_ingestions(parent_ingestion_id);
CREATE INDEX IF NOT EXISTS idx_raw_ingestions_vacancy_index ON raw_job_ingestions(vacancy_index);
```

### Ingestion Staging Model:
1. **Parent Post (`parent_ingestion_id = NULL, vacancy_index = 1, total_vacancies = N`)**:
   - Holds original verbatim caption/text, raw poster image path, source URL, and content/media SHA-256 hashes.
   - Holds normalized extracted data for the first vacancy.
2. **Sibling Sub-Vacancies (`parent_ingestion_id = parent_id, vacancy_index = 2..N, total_vacancies = N`)**:
   - Reuses identical poster image path and source metadata without file duplication.
   - Holds its own distinct `extracted_data`, `matched_job_id`, `duplicate_score`, and status lifecycle (`PENDING_REVIEW` $\rightarrow$ `APPROVED`).

---

## 4. Multi-Job Detection & Taxonomy Expansion

The local deterministic parser and normalizer were expanded to handle the wide variety of Tiruppur garment roles and bilingual terminology:

| Raw Input / Title | Detected Department | Canonical Job Role |
| :--- | :--- | :--- |
| `Training Manager (Sewing)` | **Sewing** | `Training Manager` |
| `Sewing Trainer` | **Sewing** | `Sewing Trainer` |
| `IT Assistant` / `IT Executive` | **IT** | `IT Assistant` |
| `Fabric DEO` / `Store DEO` | **Stores** | `Fabric DEO` |
| `Data Entry Operator` | **Stores** | `Data Entry Operator (DEO)` |
| `Costing Executive` | **Merchandising** | `Costing Executive` |
| `Costing Manager` | **Merchandising** | `Costing Manager` |
| `Production Supervisor` | **Production** | `Production Supervisor` |
| `Cutting Master` / `கட்டிங் மாஸ்டர்` | **Cutting** | `Cutting Master` |
| `Quality Inspector` / `குவாலிட்டி` | **Quality** | `Quality Inspector` |

---

## 5. Role-Specific Attribute Extraction

The parser extracts role-specific details when present on individual lines or subsequent sub-lines:

```text
[DEMO] Rayapuram Apparel Unit requires:
- Senior Merchandiser (5-8 yrs) - Salary: 45000 - 55000
- Sewing Line Supervisor (2-4 yrs) - Salary: 25000 - 30000

Contact: 9876511111
```

- **Vacancy 1 (Senior Merchandiser)**:
  - Experience: `5 - 8 years`
  - Salary: `₹45,000 - ₹55,000`
  - Department: `Merchandising`
- **Vacancy 2 (Sewing Line Supervisor)**:
  - Experience: `2 - 4 years`
  - Salary: `₹25,000 - ₹30,000`
  - Department: `Sewing`
- **Shared Provenance**: Both inherit company `Rayapuram Apparel Unit`, location `Tiruppur`, and phone `+91 98765 11111`.

---

## 6. Deduplication Engine Guardrails

A critical requirement is avoiding false positive duplicate merges across different roles from the same post or company.

1. **Role Guardrail in Deduplication**:
   - If two vacancies share the same `content_hash` or recruiter phone number, but have different roles (e.g. `Accountant` vs `Merchandiser`), the deduplication engine returns `score = 0.0` and band `DISTINCT_JOB`.
   - Role similarity threshold $\ge 0.65$ is required before duplicate scoring activates.
2. **Re-Import Duplicate Catching**:
   - If the exact same 4-job announcement is re-imported after approval, all 4 vacancies are matched against their respective approved master jobs ($\ge 0.85$ score), preventing public duplication.

---

## 7. Bulk Approval & Batch Actions

The endpoint `POST /api/admin/ingestion/bulk-approve` enables atomic and partial batch publishing:

```json
{
  "success": true,
  "total": 4,
  "approved_count": 4,
  "merged_count": 0,
  "review_required_count": 0,
  "results": [
    { "ingestion_id": 3919, "action": "APPROVED", "job_id": 49, "slug": "demo-abc-garments-training-manager-b827e1" },
    { "ingestion_id": 3920, "action": "APPROVED", "job_id": 50, "slug": "demo-abc-garments-it-assistant-2f19a0" },
    { "ingestion_id": 3921, "action": "APPROVED", "job_id": 51, "slug": "demo-abc-garments-fabric-deo-79e8cd" },
    { "ingestion_id": 3922, "action": "APPROVED", "job_id": 52, "slug": "demo-abc-garments-costing-executive-49a37c" }
  ]
}
```

- **Non-blocking Partial Success**: If 3 jobs are valid and 1 requires review, 3 are published immediately while the 4th remains in `PENDING_REVIEW` for manual correction.

---

## 8. Admin UI & Analysis Result Cockpit

The Admin Ingestion tab (`/admin`) features:
1. **Primary Button**: `🧠 ANALYZE JOB POST`.
2. **Analysis Result Container (`#inlineImportResult`)**:
   - **Header Bar**: Displays `Detected Vacancies: N`, company name, location, source attribution, and `₹0 Paid AI Cost` badge.
   - **Card Grid**: Responsive cards for each detected vacancy (Job 1, Job 2, Job 3, ...) showing role, department, salary, experience, phone, confidence pill, and duplicate badge.
   - **Batch Action Buttons**:
     - `[ 🚀 Approve All & Publish ]` $\rightarrow$ Triggers bulk approval.
     - `[ Review Individually ]` $\rightarrow$ Opens full split-screen modal.
     - `[ + Import Another Post ]` $\rightarrow$ Resets form for next post.
3. **Queue Table Integration**:
   - Displays multi-job badge (e.g. `Vac 1/4`, `Vac 2/4`) in the role column for full visibility.

---

## 9. Comprehensive Verification & Regression Results

### Test Suite Execution Summary:

| Test Suite File | Focus Area | Tests Executed | Passed | Failed | Status |
| :--- | :--- | :---: | :---: | :---: | :---: |
| `scratch/test_step3d5_smart_multi_job.py` | Multi-Job Segmentation, Roles & Bulk Approve | 31 | 31 | 0 | **PASS** |
| `scratch/test_step3d_gateway.py` | Multi-Source Import Gateway & Observability | 32 | 32 | 0 | **PASS** |
| `scratch/test_step2_direct.py` | Public Jobs, Soft-Delete & Candidate Safety | 29 | 29 | 0 | **PASS** |
| `scratch/test_admin_ui_gateway_fix.py` | Admin HTML DOM, CSS & Mobile Responsiveness | 25 | 25 | 0 | **PASS** |
| **Total Test Suite** | **Full System Integrity** | **117** | **117** | **0** | **PASS** |

---

## 10. Cost & Performance Audit

- **Paid AI Cost:** ₹0.00 (100% deterministic local extraction for text announcements).
- **Processing Time:** $< 45\text{ ms}$ per 4-job announcement.
- **Image Reuse:** 1 physical file on disk shared across all child records via foreign keys.
- **Data Integrity:** All sample tests strictly use `[DEMO]` prefix; no real company data fabricated.
