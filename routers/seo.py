import os
import re
import html
import logging
import datetime
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException, Response, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, FileResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["SEO & Static Hubs"])

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CANONICAL_DOMAIN = "https://tirupurgarment.in"

# DB helper injectors (will be configured by app.py)
db_helpers = {
    "db_enabled": False,
    "query_db": None
}

def init_seo_db_helpers(enabled: bool, query_fn):
    db_helpers["db_enabled"] = enabled
    db_helpers["query_db"] = query_fn

# --- 1. ROBOTS.TXT ---
@router.get("/robots.txt", response_class=PlainTextResponse)
def get_robots_txt():
    """
    Returns safe crawler directives.
    Allows all search engines to access public HTML, CSS, JS, and media assets.
    Excludes private admin and session-dependent API endpoints.
    Declares sitemap location.
    """
    content = f"""User-agent: *
Allow: /
Disallow: /admin
Disallow: /admin/
Disallow: /api/admin/

Sitemap: {CANONICAL_DOMAIN}/sitemap.xml
"""
    return PlainTextResponse(content=content, media_type="text/plain")


# --- 2. SITEMAP.XML ---
@router.get("/sitemap.xml")
def get_sitemap_xml():
    """
    Generates a production-ready, valid XML sitemap.
    Static: Only real, public canonical URLs.
    Dynamic: Real active published jobs queried from the database.
    SAFETY: If database query fails, outputs static sitemap cleanly without failing or injecting fake jobs.
    """
    today_iso = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")

    static_urls = [
        {"loc": f"{CANONICAL_DOMAIN}/", "priority": "1.0", "changefreq": "daily"},
        {"loc": f"{CANONICAL_DOMAIN}/jobs", "priority": "0.9", "changefreq": "daily"},
        {"loc": f"{CANONICAL_DOMAIN}/tools", "priority": "0.8", "changefreq": "weekly"},
        {"loc": f"{CANONICAL_DOMAIN}/tools/sam-calculator", "priority": "0.9", "changefreq": "weekly"},
        {"loc": f"{CANONICAL_DOMAIN}/services", "priority": "0.8", "changefreq": "monthly"},
        {"loc": f"{CANONICAL_DOMAIN}/services/report-automation", "priority": "0.8", "changefreq": "monthly"},
        {"loc": f"{CANONICAL_DOMAIN}/services/excel-automation", "priority": "0.8", "changefreq": "monthly"},
        {"loc": f"{CANONICAL_DOMAIN}/services/garment-production-planning", "priority": "0.8", "changefreq": "monthly"},
        {"loc": f"{CANONICAL_DOMAIN}/services/garment-erp", "priority": "0.8", "changefreq": "monthly"},
        {"loc": f"{CANONICAL_DOMAIN}/blog", "priority": "0.8", "changefreq": "weekly"},
        {"loc": f"{CANONICAL_DOMAIN}/blog/what-is-sam-in-garment-manufacturing", "priority": "0.8", "changefreq": "monthly"},
        {"loc": f"{CANONICAL_DOMAIN}/blog/how-to-calculate-garment-production-target-and-efficiency", "priority": "0.8", "changefreq": "monthly"},
        {"loc": f"{CANONICAL_DOMAIN}/blog/tiruppur-garment-industry-jobs-and-hiring-guide", "priority": "0.8", "changefreq": "monthly"},
        {"loc": f"{CANONICAL_DOMAIN}/blog/garment-excel-automation-vs-erp", "priority": "0.8", "changefreq": "monthly"},
        {"loc": f"{CANONICAL_DOMAIN}/jobs/merchandiser-jobs-tiruppur", "priority": "0.8", "changefreq": "daily"},
        {"loc": f"{CANONICAL_DOMAIN}/jobs/production-jobs-tiruppur", "priority": "0.8", "changefreq": "daily"},
        {"loc": f"{CANONICAL_DOMAIN}/jobs/quality-jobs-tiruppur", "priority": "0.8", "changefreq": "daily"},
        {"loc": f"{CANONICAL_DOMAIN}/jobs/cutting-jobs-tiruppur", "priority": "0.8", "changefreq": "daily"},
        {"loc": f"{CANONICAL_DOMAIN}/jobs/sewing-jobs-tiruppur", "priority": "0.8", "changefreq": "daily"},
    ]

    job_urls = []
    if db_helpers["db_enabled"] and db_helpers["query_db"]:
        try:
            query = """
                SELECT slug, published_at, created_at
                FROM jobs
                WHERE LOWER(status) = 'published'
                  AND COALESCE(is_archived, FALSE) = FALSE
                  AND slug IS NOT NULL AND slug != '';
            """
            rows = db_helpers["query_db"](query)
            for r in rows:
                slug = r.get("slug")
                if not slug:
                    continue
                pub_date = r.get("published_at") or r.get("created_at")
                lastmod = pub_date.strftime("%Y-%m-%d") if isinstance(pub_date, (datetime.datetime, datetime.date)) else today_iso
                job_urls.append({
                    "loc": f"{CANONICAL_DOMAIN}/jobs/{slug}",
                    "lastmod": lastmod,
                    "priority": "0.7",
                    "changefreq": "weekly"
                })
        except Exception as e:
            logger.warning(f"Database sitemap query warning (safely proceeding with static URLs): {e}")

    xml_lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    ]

    for item in static_urls:
        xml_lines.append("  <url>")
        xml_lines.append(f"    <loc>{item['loc']}</loc>")
        xml_lines.append(f"    <lastmod>{item.get('lastmod', today_iso)}</lastmod>")
        xml_lines.append(f"    <changefreq>{item['changefreq']}</changefreq>")
        xml_lines.append(f"    <priority>{item['priority']}</priority>")
        xml_lines.append("  </url>")

    for item in job_urls:
        xml_lines.append("  <url>")
        xml_lines.append(f"    <loc>{item['loc']}</loc>")
        xml_lines.append(f"    <lastmod>{item['lastmod']}</lastmod>")
        xml_lines.append(f"    <changefreq>{item['changefreq']}</changefreq>")
        xml_lines.append(f"    <priority>{item['priority']}</priority>")
        xml_lines.append("  </url>")

    xml_lines.append("</urlset>")
    xml_content = "\n".join(xml_lines)

    return Response(content=xml_content, media_type="application/xml; charset=utf-8")


# --- 3. TOOLS & SERVICES HUBS ---
@router.get("/tools", response_class=FileResponse)
def get_tools_page():
    return FileResponse(os.path.join(BASE_DIR, "tools.html"))

@router.get("/tools/sam-calculator", response_class=FileResponse)
def get_sam_calculator():
    return FileResponse(os.path.join(BASE_DIR, "sam_calculator.html"))

@router.get("/services", response_class=FileResponse)
def get_services_page():
    return FileResponse(os.path.join(BASE_DIR, "services.html"))

@router.get("/blog", response_class=FileResponse)
def get_blog_page():
    return FileResponse(os.path.join(BASE_DIR, "blog.html"))


# --- 4. SERVICE DETAIL PAGES ---
SERVICE_DATA = {
    "report-automation": {
        "title": "Garment Daily Production & Export Report Automation | DigiGarment",
        "description": "Automate daily sewing line reports, hourly output trackers, WIP status sheets, and consolidated management dashboards for Tiruppur garment export houses.",
        "h1": "Daily Production & Export Report Automation for Garment Factories",
        "icon": "⌁",
        "problem": "Garment factory supervisors and data entry staff spend 2 to 4 hours daily compiling manual handwritten production logs into fragmented Excel workbooks. This causes delay in daily WIP visibility, calculation errors, and slow decision-making on the sewing floor.",
        "solution": "DigiGarment deploys automated data ingestion and reporting workflows that consolidate cutting, sewing line output, finishing, and packing numbers automatically into clean, standardized executive dashboards.",
        "features": [
            "Automated Hourly Line Output & Efficiency calculation",
            "Consolidated Daily Production Report (DPR) generated on schedule",
            "WIP Bottleneck Tracker between Cutting, Sewing & Finishing",
            "Secure automated email/WhatsApp distribution to management"
        ],
        "faq": [
            {
                "q": "How does automated DPR report generation work?",
                "a": "Daily production counts entered at shopfloor stations or supervisors' spreadsheets are automatically consolidated, validated, and computed into summary reports without manual copy-pasting."
            },
            {
                "q": "Can it integrate with our existing spreadsheet formats?",
                "a": "Yes. Our automation scripts map directly to your existing production log templates and output formats."
            }
        ]
    },
    "excel-automation": {
        "title": "Garment Industry Excel & Macro Automation | DigiGarment",
        "description": "Convert manual Excel spreadsheets into automated workflows. Custom formulas, Power Query pipelines, and Python automation for Tiruppur garment manufacturers.",
        "h1": "Excel & Spreadsheet Workflow Automation for Garment Industries",
        "icon": "▤",
        "problem": "Garment merchandisers, sampling teams, and store managers manage complex orders using multiple disconnected spreadsheets. Broken formulas, version mismatch, and manual data copy-paste lead to costly fabric ordering mistakes and shipment delays.",
        "solution": "We build robust Excel macro automation, Power Query models, and automated data pipelines that link order BOMs, fabric consumption, trim inventories, and shipment schedules with zero manual friction.",
        "features": [
            "Automated Fabric Consumption & Costing Calculation sheets",
            "One-click Tech Pack BOM consolidation into Purchase Orders",
            "Dynamic Trim Inventory Reorder & Tracking spreadsheets",
            "Automated Salary & Payslip generation pipelines"
        ],
        "faq": [
            {
                "q": "Do we need to buy expensive software licenses for Excel automation?",
                "a": "No. Our solutions work directly inside your existing Microsoft Excel or Google Sheets environment using built-in automation and lightweight scripts."
            },
            {
                "q": "Is training provided for our merchandising and store staff?",
                "a": "Yes, complete operational walkthroughs and documented templates are provided to ensure your team operates the automated sheets effortlessly."
            }
        ]
    },
    "garment-production-planning": {
        "title": "Garment Production Planning & Line Balancing | DigiGarment",
        "description": "Digital production planning, pitch time computation, and sewing line balancing solutions for Tiruppur apparel manufacturers and garment export units.",
        "h1": "Garment Production Planning & Sewing Line Balancing Solutions",
        "icon": "⚙",
        "problem": "Unbalanced sewing lines create severe bottlenecks where fast operations wait for slower operations, resulting in low overall line efficiency (often dropping below 50%) and high operator overtime costs.",
        "solution": "We provide industrial engineering planning frameworks and digital line balancing tools that calculate pitch time, workstation allocations, and operator target quotas based on accurate SAM/SMV operational values.",
        "features": [
            "Automatic Pitch Time calculation and Theoretical Workstation sizing",
            "Operation Breakdown sequencing and Line Balancing matrix",
            "Hourly target adjustment based on operator efficiency curves",
            "Real-time bottleneck identification across assembly lines"
        ],
        "faq": [
            {
                "q": "How does line balancing improve sewing floor productivity?",
                "a": "By equalizing the workload assigned to each workstation based on operation SAM, idle operator waiting time is minimized and continuous garment flow is maintained."
            },
            {
                "q": "Can this be applied to knitted apparel and t-shirt lines in Tiruppur?",
                "a": "Yes, our line balancing models are specifically tailored to polo shirts, round-neck t-shirts, hoodies, and basic knitwear manufacturing."
            }
        ]
    },
    "garment-erp": {
        "title": "Garment ERP & Order Lifecycle Software | DigiGarment",
        "description": "Practical garment manufacturing ERP software covering sampling, fabric procurement, cutting, sewing, quality inspection, and export shipment tracking.",
        "h1": "Garment ERP & Order Lifecycle Tracking Software",
        "icon": "⌘",
        "problem": "Traditional enterprise ERPs are often overly complex, slow to implement, and poorly suited to the fast turnaround rhythms of Tiruppur knitwear export houses.",
        "solution": "DigiGarment delivers lightweight, intuitive digital order lifecycle tracking designed specifically for apparel workflows—from sample approval and fabric yarn dyeing to final carton packing.",
        "features": [
            "Style-wise Time & Action (T&A) Milestone calendar",
            "Fabric yarn, knitting, dyeing & compacting process tracker",
            "Production Floor Cutting-to-Packing order progression",
            "Defect logging and AQL quality inspection reports"
        ],
        "faq": [
            {
                "q": "How long does implementation take for a garment factory?",
                "a": "Because our modules are focused and lightweight, core order tracking and reporting can be configured and deployed within days."
            },
            {
                "q": "Can multiple department users access the system simultaneously?",
                "a": "Yes, role-based access allows merchandisers, production supervisors, storekeepers, and management to access their respective data seamlessly."
            }
        ]
    }
}

@router.get("/services/{slug}", response_class=HTMLResponse)
def get_service_detail_page(slug: str):
    service = SERVICE_DATA.get(slug)
    if not service:
        raise HTTPException(status_code=404, detail="Service not found")

    canonical_url = f"{CANONICAL_DOMAIN}/services/{slug}"
    escaped_title = html.escape(service["title"])
    escaped_desc = html.escape(service["description"])
    escaped_h1 = html.escape(service["h1"])

    features_html = "".join(f"<li style='margin-bottom: 10px; color: #334155;'>✓ {html.escape(f)}</li>" for f in service["features"])
    
    faq_html = ""
    faq_schema_items = []
    for item in service["faq"]:
        q_esc = html.escape(item["q"])
        a_esc = html.escape(item["a"])
        faq_html += f"""
        <details style="background: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 8px; padding: 16px; margin-bottom: 12px; cursor: pointer;">
            <summary style="font-weight: 700; color: #081226; font-size: 15px;">{q_esc}</summary>
            <p style="margin: 10px 0 0 0; color: #64748B; font-size: 14px; line-height: 1.6;">{a_esc}</p>
        </details>
        """
        faq_schema_items.append({
            "@type": "Question",
            "name": item["q"],
            "acceptedAnswer": {
                "@type": "Answer",
                "text": item["a"]
            }
        })

    import json
    faq_schema_json = json.dumps({
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "Service",
                "name": service["h1"],
                "provider": {
                    "@type": "Organization",
                    "name": "DigiGarment",
                    "url": CANONICAL_DOMAIN
                },
                "areaServed": "Tiruppur, Tamil Nadu, India",
                "description": service["description"]
            },
            {
                "@type": "BreadcrumbList",
                "itemListElement": [
                    {"@type": "ListItem", "position": 1, "name": "Home", "item": f"{CANONICAL_DOMAIN}/"},
                    {"@type": "ListItem", "position": 2, "name": "Services", "item": f"{CANONICAL_DOMAIN}/services"},
                    {"@type": "ListItem", "position": 3, "name": service["h1"], "item": canonical_url}
                ]
            },
            {
                "@type": "FAQPage",
                "mainEntity": faq_schema_items
            }
        ]
    })

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{escaped_title}</title>
    <meta name="description" content="{escaped_desc}">
    <link rel="canonical" href="{canonical_url}">

    <!-- Open Graph -->
    <meta property="og:title" content="{escaped_title}">
    <meta property="og:description" content="{escaped_desc}">
    <meta property="og:url" content="{canonical_url}">
    <meta property="og:type" content="website">
    <meta property="og:image" content="{CANONICAL_DOMAIN}/assets/images/hero-automation.jpg">
    <meta name="twitter:card" content="summary_large_image">

    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Plus+Jakarta+Sans:wght@700;800&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="/css/styles.css">

    <script type="application/ld+json">
    {faq_schema_json}
    </script>
    <style>
        :root {{
            --dg-navy: #081226;
            --dg-red: #9E1B32;
            --dg-red-hover: #b92a43;
            --dg-slate: #64748B;
            --dg-bg: #F8FAFC;
        }}
        body {{
            background-color: var(--dg-bg);
            font-family: 'Inter', sans-serif;
            color: #0F172A;
            margin: 0;
            padding: 0;
        }}
        .service-hero {{
            background: linear-gradient(135deg, #081226 0%, #111E38 100%);
            color: #ffffff;
            padding: 60px 0 48px 0;
            text-align: center;
        }}
        .service-hero h1 {{
            font-family: 'Plus Jakarta Sans', sans-serif;
            font-size: 32px;
            font-weight: 800;
            margin: 0 0 16px 0;
            line-height: 1.3;
        }}
        .service-hero p {{
            color: #94A3B8;
            font-size: 16px;
            max-width: 700px;
            margin: 0 auto;
            line-height: 1.6;
        }}
        .breadcrumbs-bar {{
            background: #ffffff;
            border-bottom: 1px solid #E2E8F0;
            padding: 12px 0;
            font-size: 13px;
        }}
        .breadcrumbs-bar a {{ color: var(--dg-slate); text-decoration: none; }}
        .breadcrumbs-bar a:hover {{ color: var(--dg-red); }}
        .breadcrumbs-bar span {{ color: #CBD5E1; margin: 0 8px; }}
        .breadcrumbs-bar strong {{ color: var(--dg-navy); }}
        .content-card {{
            background: #ffffff;
            border-radius: 12px;
            padding: 40px;
            border: 1px solid #E2E8F0;
            margin: 40px auto;
            max-width: 900px;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.03);
        }}
        .btn-cta {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            padding: 14px 28px;
            background: var(--dg-red);
            color: #ffffff;
            font-weight: 700;
            border-radius: 8px;
            text-decoration: none;
            transition: background 0.2s;
            margin-top: 24px;
        }}
        .btn-cta:hover {{ background: var(--dg-red-hover); }}
    </style>
</head>
<body>
    <header class="site-header">
        <div class="container nav-wrap">
            <a class="brand" href="/">
                <img src="/assets/images/logo-light.png" alt="DigiGarment Logo" style="height: 38px;">
            </a>
            <nav class="nav">
                <a href="/">Home</a>
                <a href="/jobs">Tiruppur Jobs</a>
                <a href="/tools">Tools</a>
                <a class="active" href="/services">Services</a>
                <a href="/blog">Blog</a>
                <a href="/#contact">Contact</a>
            </nav>
        </div>
    </header>

    <div class="breadcrumbs-bar">
        <div class="container">
            <a href="/">Home</a>
            <span>›</span>
            <a href="/services">Services</a>
            <span>›</span>
            <strong>{escaped_h1}</strong>
        </div>
    </div>

    <section class="service-hero">
        <div class="container">
            <h1>{escaped_h1}</h1>
            <p>{escaped_desc}</p>
        </div>
    </section>

    <main class="container">
        <div class="content-card">
            <h2 style="font-size: 22px; color: #081226; font-weight: 700; margin-top: 0;">Operational Challenges in Garment Units</h2>
            <p style="color: #64748B; font-size: 15px; line-height: 1.7;">{html.escape(service["problem"])}</p>

            <h2 style="font-size: 22px; color: #081226; font-weight: 700; margin-top: 32px;">DigiGarment Automation Solution</h2>
            <p style="color: #64748B; font-size: 15px; line-height: 1.7;">{html.escape(service["solution"])}</p>

            <h2 style="font-size: 22px; color: #081226; font-weight: 700; margin-top: 32px;">Core Capabilities</h2>
            <ul style="list-style: none; padding: 0; margin: 16px 0 32px 0;">
                {features_html}
            </ul>

            <h2 style="font-size: 22px; color: #081226; font-weight: 700; margin-top: 32px;">Frequently Asked Questions</h2>
            {faq_html}

            <div style="text-align: center; margin-top: 40px; padding-top: 30px; border-top: 1px solid #E2E8F0;">
                <h3 style="margin: 0 0 8px 0; color: #081226;">Ready to automate your garment workflows?</h3>
                <p style="color: #64748B; margin: 0 0 16px 0;">Talk to our automation engineers in Tiruppur for a tailored consultation.</p>
                <a href="/#contact" class="btn-cta">Contact DigiGarment Team →</a>
            </div>
        </div>
    </main>

    <footer style="background: #081226; color: #94A3B8; padding: 40px 0 20px 0; text-align: center; font-size: 14px;">
        <p style="margin-bottom: 12px;">© 2026 DigiGarment. Practical digital transformation for garment manufacturing.</p>
        <div>
            <a href="/" style="color: #94A3B8; margin: 0 10px; text-decoration: none;">Home</a>
            <a href="/jobs" style="color: #94A3B8; margin: 0 10px; text-decoration: none;">Tiruppur Jobs</a>
            <a href="/tools/sam-calculator" style="color: #94A3B8; margin: 0 10px; text-decoration: none;">SAM Calculator</a>
            <a href="/tools" style="color: #94A3B8; margin: 0 10px; text-decoration: none;">Tools Hub</a>
            <a href="/blog" style="color: #94A3B8; margin: 0 10px; text-decoration: none;">Blog</a>
        </div>
    </footer>
</body>
</html>
"""


# --- 5. BLOG POST PAGES ---
BLOG_ARTICLES = {
    "what-is-sam-in-garment-manufacturing": {
        "title": "What is SAM in Garment Manufacturing? Standard Allowed Minutes Formula & Calculation",
        "description": "Complete industrial engineering guide to Standard Allowed Minutes (SAM) and SMV in apparel manufacturing. Learn formulas, allowances, and cycle times.",
        "h1": "What is SAM in Garment Manufacturing? Complete Guide to Standard Allowed Minutes",
        "date": "2026-09-01",
        "category": "Industrial Engineering",
        "content_html": """
        <p>In garment manufacturing and industrial engineering (IE), <strong>Standard Allowed Minutes (SAM)</strong> is one of the foundational metrics used to measure productivity, calculate manufacturing cost, balance sewing lines, and determine worker capacity.</p>
        
        <h2>Definition of SAM and SMV</h2>
        <p><strong>Standard Allowed Minutes (SAM)</strong>—also referred to internationally as <strong>Standard Minute Value (SMV)</strong>—is the total time allocated for a qualified operator to complete a specific garment construction operation working at a standard rating, including necessary handling time and industrial allowances.</p>
        
        <h2>How SAM is Calculated</h2>
        <p>The standard calculation for garment operation SAM consists of three primary components:</p>
        <ol>
            <li><strong>Machine Sewing Time:</strong> Calculated from the stitch length, stitch density (SPI or SPC), and sewing machine operational speed (RPM).</li>
            <li><strong>Handling and Positioning Time:</strong> The duration required by the operator to pick, align, position, reposition, and dispose of the garment fabric panels.</li>
            <li><strong>Industrial Allowances:</strong> Percentage adjustments added for personal needs (3–5%), physical fatigue (2–4%), minor machine delays (1–3%), and bundle handling (2–4%).</li>
        </ol>

        <div style="background: #081226; color: #F8FAFC; padding: 20px; border-radius: 8px; font-family: monospace; font-size: 14px; margin: 24px 0;">
            SAM (Minutes) = [(Machine Sewing Time + Handling Time) × (1 + Total Allowance % / 100)] / 60
        </div>

        <h2>Why SAM Accuracy Matters in Apparel Production</h2>
        <p>Accurate SAM calculations allow production planners to:</p>
        <ul>
            <li><strong>Determine Realistic Line Targets:</strong> Accurately calculate expected hourly garment output based on the number of sewing machines on the line.</li>
            <li><strong>Accurate Costing for Buyers:</strong> Calculate exact labor cost per garment unit for export price quotations.</li>
            <li><strong>Identify Bottlenecks:</strong> Highlight high-cycle-time operations that need support operators or workstation restructuring.</li>
        </ul>

        <div style="background: #FFFBFB; border-left: 4px solid #9E1B32; padding: 16px; margin: 32px 0;">
            <strong>Try our free tool:</strong> Use the <a href="/tools/sam-calculator" style="color: #9E1B32; font-weight: 700;">DigiGarment SAM / SMV Calculator</a> to compute operation minutes and export style breakdown sheets instantly.
        </div>
        """
    },
    "how-to-calculate-garment-production-target-and-efficiency": {
        "title": "How to Calculate Garment Production Target & Line Efficiency | DigiGarment",
        "description": "Step-by-step practical formulas for calculating operator hourly targets, shift production quotas, pitch time, and line efficiency in apparel factories.",
        "h1": "How to Calculate Garment Production Target and Sewing Line Efficiency",
        "date": "2026-09-05",
        "category": "Production Planning",
        "content_html": """
        <p>Setting realistic production targets on garment sewing floors is essential for meeting shipment deadlines and controlling manufacturing costs. In this guide, we break down the exact mathematical formulas used by industrial engineers in Tiruppur textile units.</p>

        <h2>1. Calculating Hourly Target from SAM</h2>
        <p>At 100% operator efficiency, the hourly production target for a single workstation is:</p>
        <div style="background: #081226; color: #F8FAFC; padding: 16px; border-radius: 8px; font-family: monospace; font-size: 14px; margin: 16px 0;">
            Workstation Target (Pcs/Hour @ 100%) = 60 / Operation SAM
        </div>

        <h2>2. Calculating Sewing Line Target</h2>
        <p>For an entire sewing line composed of multiple operators working on a complete style (e.g. Polo T-Shirt with Total Style SAM of 18 minutes, operated by 30 workers):</p>
        <div style="background: #081226; color: #F8FAFC; padding: 16px; border-radius: 8px; font-family: monospace; font-size: 14px; margin: 16px 0;">
            Line Target/Hour (@ 100%) = (Number of Operators × 60) / Total Style SAM
        </div>
        <p>For realistic floor targets factoring in expected line efficiency (e.g. 75% efficiency):</p>
        <div style="background: #081226; color: #F8FAFC; padding: 16px; border-radius: 8px; font-family: monospace; font-size: 14px; margin: 16px 0;">
            Planned Target/Hour = Line Target/Hour (@ 100%) × (Target Efficiency % / 100)
        </div>

        <h2>3. Calculating Daily Line Efficiency Percentage</h2>
        <p>At the end of an 8-hour shift, overall line efficiency is calculated by comparing actual finished pieces against total available working minutes:</p>
        <div style="background: #081226; color: #F8FAFC; padding: 16px; border-radius: 8px; font-family: monospace; font-size: 14px; margin: 16px 0;">
            Line Efficiency (%) = [(Total Pieces Produced × Style SAM) / (Number of Operators × Total Shift Minutes)] × 100
        </div>

        <h2>Summary Takeaways</h2>
        <p>Regular daily monitoring of these calculations prevents surprise delays, ensures fair operator incentive allocation, and maintains continuous garment floor productivity.</p>
        """
    },
    "tiruppur-garment-industry-jobs-and-hiring-guide": {
        "title": "Tiruppur Garment Industry Career Guide: Roles, Skills & Hiring | DigiGarment",
        "description": "Comprehensive guide to apparel manufacturing careers in Tiruppur. Responsibilities and required skills for Merchandisers, Pattern Masters, QC, and Production Supervisors.",
        "h1": "Tiruppur Garment Industry Career Guide: Key Roles & Technical Skills",
        "date": "2026-09-10",
        "category": "Garment Careers",
        "content_html": """
        <p>Tiruppur is known globally as the knitwear manufacturing capital of India, producing cotton knitwear, sportswear, and fashion apparel for top international brands. The industry employs hundreds of thousands of technical, managerial, and operational professionals.</p>

        <h2>Key Job Roles in Tiruppur Export Houses</h2>
        
        <h3>1. Garment Merchandiser (Sampling & Production)</h3>
        <p>Merchandisers bridge communication between overseas buyers and factory floor departments. Responsibilities include buyer sample follow-ups, costing, raw material sourcing, lab dip approvals, and Time & Action (T&A) execution.</p>

        <h3>2. Pattern Master (Manual & CAD)</h3>
        <p>Pattern masters create base patterns, compute shrinkage allowances for knitted fabrics, and produce efficient cutting markers using CAD software (Optitex, Gerber, Lectra) to maximize fabric utilization.</p>

        <h3>3. Quality Controller & AQL Supervisor</h3>
        <p>Quality supervisors perform inline sewing inspections and final shipment audits using international AQL (Acceptable Quality Level 2.5/4.0) standards to prevent defect escapes.</p>

        <h3>4. Cutting Master & Line In-charge</h3>
        <p>Floor supervisors manage operator machine allocations, monitor daily production targets, and ensure bundle flow through the assembly line.</p>

        <div style="background: #FFFBFB; border-left: 4px solid #9E1B32; padding: 16px; margin: 32px 0;">
            <strong>Looking for openings in Tiruppur?</strong> Browse verified vacancies on our <a href="/jobs" style="color: #9E1B32; font-weight: 700;">Tiruppur Garment Jobs Portal</a> or submit your profile for direct factory matching.
        </div>
        """
    },
    "garment-excel-automation-vs-erp": {
        "title": "Garment Excel Automation vs ERP: Practical Decision Guide | DigiGarment",
        "description": "When should an apparel manufacturer automate Excel spreadsheets versus investing in a full ERP software system? Practical comparison for garment businesses.",
        "h1": "Garment Excel Automation vs ERP: Which Solution Fits Your Factory?",
        "date": "2026-09-12",
        "category": "Digital Transformation",
        "content_html": """
        <p>Garment factory owners in Tiruppur frequently debate whether to invest in large-scale ERP software or enhance their existing spreadsheet operations with targeted automation. Both approaches have distinct advantages depending on factory size, order volume, and team digital maturity.</p>

        <h2>When Custom Excel Automation is the Best Choice</h2>
        <ul>
            <li><strong>Quick Implementation:</strong> Custom macros, Power Query workflows, and Python data pipelines can be deployed in days without halting daily operations.</li>
            <li><strong>High Team Adoption:</strong> Staff are already familiar with Excel, eliminating long training cycles.</li>
            <li><strong>Low Cost:</strong> Requires zero recurring software license fees per seat.</li>
            <li><strong>Targeted Bottleneck Removal:</strong> Solves specific daily pain points such as fabric calculation sheets, daily production reports, or salary slip generation.</li>
        </ul>

        <h2>When to Transition to a Garment ERP System</h2>
        <ul>
            <li><strong>Multi-Location Operations:</strong> When data must sync in real time across multiple spinning, knitting, processing, and sewing factories.</li>
            <li><strong>Strict Audit & Role Permissions:</strong> When access control and change logging are required for buyer compliance.</li>
            <li><strong>End-to-End Inventory Traceability:</strong> When barcoding and roll-level fabric inventory tracking are mandated by international buyers.</li>
        </ul>

        <h2>The Hybrid Approach</h2>
        <p>Many successful Tiruppur manufacturers adopt a hybrid approach: using automated Excel tools for floor-level reporting and agile merchandising, while integrating them with lightweight database backends for central reporting.</p>
        """
    }
}

@router.get("/blog/{slug}", response_class=HTMLResponse)
def get_blog_detail_page(slug: str):
    article = BLOG_ARTICLES.get(slug)
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")

    canonical_url = f"{CANONICAL_DOMAIN}/blog/{slug}"
    escaped_title = html.escape(article["title"])
    escaped_desc = html.escape(article["description"])
    escaped_h1 = html.escape(article["h1"])

    import json
    article_schema_json = json.dumps({
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "BlogPosting",
                "headline": article["h1"],
                "description": article["description"],
                "url": canonical_url,
                "datePublished": article["date"],
                "dateModified": article["date"],
                "author": {
                    "@type": "Organization",
                    "name": "DigiGarment Engineering Team",
                    "url": CANONICAL_DOMAIN
                },
                "publisher": {
                    "@type": "Organization",
                    "name": "DigiGarment",
                    "url": CANONICAL_DOMAIN,
                    "logo": {
                        "@type": "ImageObject",
                        "url": f"{CANONICAL_DOMAIN}/assets/images/logo-light.png"
                    }
                }
            },
            {
                "@type": "BreadcrumbList",
                "itemListElement": [
                    {"@type": "ListItem", "position": 1, "name": "Home", "item": f"{CANONICAL_DOMAIN}/"},
                    {"@type": "ListItem", "position": 2, "name": "Blog", "item": f"{CANONICAL_DOMAIN}/blog"},
                    {"@type": "ListItem", "position": 3, "name": article["h1"], "item": canonical_url}
                ]
            }
        ]
    })

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{escaped_title}</title>
    <meta name="description" content="{escaped_desc}">
    <link rel="canonical" href="{canonical_url}">

    <!-- Open Graph -->
    <meta property="og:title" content="{escaped_title}">
    <meta property="og:description" content="{escaped_desc}">
    <meta property="og:url" content="{canonical_url}">
    <meta property="og:type" content="article">
    <meta property="og:image" content="{CANONICAL_DOMAIN}/assets/images/hero-automation.jpg">
    <meta name="twitter:card" content="summary_large_image">

    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Plus+Jakarta+Sans:wght@700;800&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="/css/styles.css">

    <script type="application/ld+json">
    {article_schema_json}
    </script>
    <style>
        :root {{
            --dg-navy: #081226;
            --dg-red: #9E1B32;
            --dg-red-hover: #b92a43;
            --dg-slate: #64748B;
            --dg-bg: #F8FAFC;
        }}
        body {{
            background-color: var(--dg-bg);
            font-family: 'Inter', sans-serif;
            color: #0F172A;
            margin: 0;
            padding: 0;
        }}
        .blog-post-hero {{
            background: linear-gradient(135deg, #081226 0%, #111E38 100%);
            color: #ffffff;
            padding: 60px 0 48px 0;
            text-align: center;
        }}
        .blog-post-hero h1 {{
            font-family: 'Plus Jakarta Sans', sans-serif;
            font-size: 32px;
            font-weight: 800;
            margin: 0 0 16px 0;
            line-height: 1.3;
        }}
        .blog-meta {{
            color: #94A3B8;
            font-size: 14px;
        }}
        .breadcrumbs-bar {{
            background: #ffffff;
            border-bottom: 1px solid #E2E8F0;
            padding: 12px 0;
            font-size: 13px;
        }}
        .breadcrumbs-bar a {{ color: var(--dg-slate); text-decoration: none; }}
        .breadcrumbs-bar a:hover {{ color: var(--dg-red); }}
        .breadcrumbs-bar span {{ color: #CBD5E1; margin: 0 8px; }}
        .breadcrumbs-bar strong {{ color: var(--dg-navy); }}
        .article-content {{
            background: #ffffff;
            border-radius: 12px;
            padding: 48px;
            border: 1px solid #E2E8F0;
            margin: 40px auto;
            max-width: 850px;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.03);
            font-size: 16px;
            line-height: 1.8;
            color: #334155;
        }}
        .article-content h2 {{
            color: #081226;
            font-size: 22px;
            font-weight: 700;
            margin-top: 36px;
            margin-bottom: 12px;
        }}
        .article-content h3 {{
            color: #081226;
            font-size: 18px;
            font-weight: 700;
            margin-top: 24px;
            margin-bottom: 8px;
        }}
        .article-content p {{
            margin-bottom: 20px;
        }}
        .article-content a {{
            color: var(--dg-red);
            text-decoration: underline;
        }}
    </style>
</head>
<body>
    <header class="site-header">
        <div class="container nav-wrap">
            <a class="brand" href="/">
                <img src="/assets/images/logo-light.png" alt="DigiGarment Logo" style="height: 38px;">
            </a>
            <nav class="nav">
                <a href="/">Home</a>
                <a href="/jobs">Tiruppur Jobs</a>
                <a href="/tools">Tools</a>
                <a href="/services">Services</a>
                <a class="active" href="/blog">Blog</a>
                <a href="/#contact">Contact</a>
            </nav>
        </div>
    </header>

    <div class="breadcrumbs-bar">
        <div class="container">
            <a href="/">Home</a>
            <span>›</span>
            <a href="/blog">Blog</a>
            <span>›</span>
            <strong>{escaped_h1}</strong>
        </div>
    </div>

    <section class="blog-post-hero">
        <div class="container" style="max-width: 850px; margin: 0 auto;">
            <h1>{escaped_h1}</h1>
            <div class="blog-meta">
                <span>Category: {html.escape(article['category'])}</span> • 
                <span>Published: {article['date']}</span> • 
                <span>By DigiGarment Technical Team</span>
            </div>
        </div>
    </section>

    <main class="container">
        <article class="article-content">
            {article["content_html"]}
        </article>
    </main>

    <footer style="background: #081226; color: #94A3B8; padding: 40px 0 20px 0; text-align: center; font-size: 14px;">
        <p style="margin-bottom: 12px;">© 2026 DigiGarment. Practical digital transformation for garment manufacturing.</p>
        <div>
            <a href="/" style="color: #94A3B8; margin: 0 10px; text-decoration: none;">Home</a>
            <a href="/jobs" style="color: #94A3B8; margin: 0 10px; text-decoration: none;">Tiruppur Jobs</a>
            <a href="/tools/sam-calculator" style="color: #94A3B8; margin: 0 10px; text-decoration: none;">SAM Calculator</a>
            <a href="/tools" style="color: #94A3B8; margin: 0 10px; text-decoration: none;">Tools Hub</a>
            <a href="/services" style="color: #94A3B8; margin: 0 10px; text-decoration: none;">Services</a>
        </div>
    </footer>
</body>
</html>
"""


# --- 6. JOB CATEGORY SEO HUBS ---
CATEGORY_MAPPINGS = {
    "merchandiser-jobs-tiruppur": {
        "h1": "Garment Merchandiser Jobs in Tiruppur",
        "title": "Garment Merchandiser Jobs in Tiruppur | Sampling & Production Vacancies",
        "description": "Find active garment merchandiser, junior merchandiser, and sampling coordinator jobs in Tiruppur knitwear export houses.",
        "department_keyword": "Merchandis",
        "intro": "Garment Merchandisers coordinate buyer communications, costing, sample follow-ups, and production schedules across Tiruppur knitwear export facilities.",
        "skills": ["Sampling & TNA", "Garment Costing", "Buyer Communication", "Fabric & Trim Sourcing", "ERP & Excel Workflows"],
        "faq": [
            {
                "q": "What qualifications are typical for garment merchandiser jobs in Tiruppur?",
                "a": "Degrees or diplomas in Apparel Technology, Fashion Technology, Costume Design, or Textile Engineering with practical experience in knitwear export houses."
            },
            {
                "q": "How can I apply for merchandiser vacancies on DigiGarment?",
                "a": "Click on any active vacancy below to view verified contact details (WhatsApp, phone, or email) or register your profile to apply directly."
            }
        ]
    },
    "production-jobs-tiruppur": {
        "h1": "Garment Production & Line Supervisor Jobs in Tiruppur",
        "title": "Garment Production Jobs in Tiruppur | Line Supervisor & Production In-charge",
        "description": "Explore production manager, line supervisor, and production assistant vacancies across Tiruppur garment manufacturing units.",
        "department_keyword": "Production",
        "intro": "Production supervisors manage daily sewing floor line balancing, target achievement, bundle distribution, and operator workflow in apparel factories.",
        "skills": ["Sewing Floor Supervision", "Line Balancing & Target Tracking", "Manpower Allocation", "SAM / SMV Knowledge", "WIP Management"],
        "faq": [
            {
                "q": "What are the core responsibilities of a garment production supervisor?",
                "a": "Monitoring hourly line targets, assisting sewing operators with line flow, managing attendance, and ensuring smooth bundle transitions between cutting and finishing."
            }
        ]
    },
    "quality-jobs-tiruppur": {
        "h1": "Garment Quality Controller & Auditor Jobs in Tiruppur",
        "title": "Garment Quality Jobs in Tiruppur | QC, QA & AQL Inspector Vacancies",
        "description": "Browse Quality Controller (QC), Quality Assurance (QA), and AQL fabric inspection job openings in Tiruppur export factories.",
        "department_keyword": "Quality",
        "intro": "Quality controllers verify that knitted garments meet buyer measurement tolerances, sewing defect standards, and international AQL compliance.",
        "skills": ["AQL 2.5/4.0 Standards", "Sewing Defect Identification", "Measurement Checking", "4-Point Fabric Inspection", "Inline & Endline Auditing"],
        "faq": [
            {
                "q": "What quality inspection standards are common in Tiruppur garment units?",
                "a": "AQL (Acceptable Quality Level) 2.5 for major defects and 4.0 for minor defects are widely practiced across European and US export orders."
            }
        ]
    },
    "cutting-jobs-tiruppur": {
        "h1": "Garment Cutting Master & Pattern Master Jobs in Tiruppur",
        "title": "Pattern Master & Cutting Jobs in Tiruppur | CAD & Spreading Vacancies",
        "description": "Find pattern maker, CAD marker planner, and cutting master jobs in Tiruppur apparel and knitting factories.",
        "department_keyword": "Cutting",
        "intro": "Pattern masters and cutting section specialists calculate knitwear shrinkage, engineer master patterns, and optimize fabric consumption.",
        "skills": ["Manual Pattern Grading", "Optitex / Gerber CAD", "Marker Efficiency Planning", "Fabric Shrinkage Testing", "Spreading & Lay Cutting"],
        "faq": [
            {
                "q": "Which CAD software tools are commonly used for pattern making in Tiruppur?",
                "a": "Optitex, Gerber Technology, and Lectra are among the most commonly used CAD systems in Tiruppur export units."
            }
        ]
    },
    "sewing-jobs-tiruppur": {
        "h1": "Garment Sewing Machine Technician & Line Jobs in Tiruppur",
        "title": "Garment Sewing Jobs in Tiruppur | Machine Mechanics & Floor Technicians",
        "description": "Explore sewing line technician, machine mechanic, and sewing operation supervisor vacancies in Tiruppur garment factories.",
        "department_keyword": "Sewing",
        "intro": "Sewing technicians and line in-charges maintain lockstitch, overlock, and flatlock machinery and oversee operator output on garment production lines.",
        "skills": ["SNLS / Overlock / Flatlock Maintenance", "Needle Gauge Setting", "Folder & Attachment Setup", "Line Troubleshooting", "Machine Speed Tuning"],
        "faq": [
            {
                "q": "What types of sewing machines are predominantly used in Tiruppur knitwear?",
                "a": "Single needle lockstitch (SNLS), 3/4/5-thread overlock, 3-needle flatlock (coverstitch), and specialized buttonhole/bartack machines."
            }
        ]
    }
}

@router.get("/jobs/{slug}", response_class=HTMLResponse)
def get_job_or_category_page(slug: str):
    """
    Handles both Category Hub pages (e.g. merchandiser-jobs-tiruppur)
    and specific real Job Detail pages (e.g. jr-merchandiser-7f3b4e) with server-rendered metadata & JobPosting schema.
    """
    # 1. Check if it's a known category hub
    if slug in CATEGORY_MAPPINGS:
        cat_info = CATEGORY_MAPPINGS[slug]
        canonical_url = f"{CANONICAL_DOMAIN}/jobs/{slug}"
        escaped_title = html.escape(cat_info["title"])
        escaped_desc = html.escape(cat_info["description"])
        escaped_h1 = html.escape(cat_info["h1"])

        # Query REAL matching active jobs from the database
        matching_jobs = []
        if db_helpers["db_enabled"] and db_helpers["query_db"]:
            try:
                keyword = f"%{cat_info['department_keyword']}%"
                query = """
                    SELECT j.id, j.title, j.slug, j.department, j.job_role, j.location,
                           j.salary_text, j.experience_min, j.experience_max, j.job_type,
                           c.name AS company_name
                    FROM jobs j
                    LEFT JOIN companies c ON j.company_id = c.id
                    WHERE LOWER(j.status) = 'published'
                      AND COALESCE(j.is_archived, FALSE) = FALSE
                      AND (j.department ILIKE %s OR j.job_role ILIKE %s OR j.title ILIKE %s)
                    ORDER BY j.is_featured DESC, j.published_at DESC NULLS LAST, j.id DESC
                    LIMIT 20;
                """
                matching_jobs = db_helpers["query_db"](query, (keyword, keyword, keyword))
            except Exception as e:
                logger.warning(f"Error querying jobs for category {slug}: {e}")

        jobs_list_html = ""
        if matching_jobs:
            for job in matching_jobs:
                j_title = html.escape(job.get("title") or "Garment Vacancy")
                j_slug = job.get("slug") or str(job.get("id"))
                j_loc = html.escape(job.get("location") or "Tiruppur, Tamil Nadu")
                j_company = html.escape(job.get("company_name") or "Garment Manufacturing Unit")
                j_sal = f"<span style='color: #10B981; font-weight: 600;'>{html.escape(job['salary_text'])}</span>" if job.get("salary_text") else ""
                
                jobs_list_html += f"""
                <div style="background: #ffffff; border: 1px solid #E2E8F0; border-radius: 10px; padding: 20px; margin-bottom: 16px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px;">
                    <div>
                        <h3 style="margin: 0 0 6px 0; font-size: 17px; color: #081226;"><a href="/jobs/{j_slug}" style="color: #081226; text-decoration: none;">{j_title}</a></h3>
                        <div style="font-size: 13px; color: #64748B;">🏢 {j_company} &nbsp;•&nbsp; 📍 {j_loc} &nbsp; {j_sal}</div>
                    </div>
                    <a href="/jobs/{j_slug}" style="background: #9E1B32; color: #ffffff; padding: 8px 18px; border-radius: 6px; text-decoration: none; font-size: 13px; font-weight: 600;">View Details &rarr;</a>
                </div>
                """
        else:
            jobs_list_html = """
            <div style="background: #F8FAFC; border: 1px dashed #CBD5E1; border-radius: 8px; padding: 24px; text-align: center; color: #64748B; font-size: 14px;">
                No vacancies currently published in this specific category. You can register your candidate profile below to be matched with upcoming openings.
            </div>
            """

        faq_html = ""
        faq_schema_items = []
        for f in cat_info["faq"]:
            faq_html += f"""
            <details style="background: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 8px; padding: 16px; margin-bottom: 12px; cursor: pointer;">
                <summary style="font-weight: 700; color: #081226; font-size: 15px;">{html.escape(f['q'])}</summary>
                <p style="margin: 10px 0 0 0; color: #64748B; font-size: 14px; line-height: 1.6;">{html.escape(f['a'])}</p>
            </details>
            """
            faq_schema_items.append({
                "@type": "Question",
                "name": f["q"],
                "acceptedAnswer": {"@type": "Answer", "text": f["a"]}
            })

        import json
        cat_schema_json = json.dumps({
            "@context": "https://schema.org",
            "@graph": [
                {
                    "@type": "CollectionPage",
                    "name": cat_info["h1"],
                    "description": cat_info["description"],
                    "url": canonical_url
                },
                {
                    "@type": "BreadcrumbList",
                    "itemListElement": [
                        {"@type": "ListItem", "position": 1, "name": "Home", "item": f"{CANONICAL_DOMAIN}/"},
                        {"@type": "ListItem", "position": 2, "name": "Jobs", "item": f"{CANONICAL_DOMAIN}/jobs"},
                        {"@type": "ListItem", "position": 3, "name": cat_info["h1"], "item": canonical_url}
                    ]
                },
                {
                    "@type": "FAQPage",
                    "mainEntity": faq_schema_items
                }
            ]
        })

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{escaped_title}</title>
    <meta name="description" content="{escaped_desc}">
    <link rel="canonical" href="{canonical_url}">

    <!-- Open Graph -->
    <meta property="og:title" content="{escaped_title}">
    <meta property="og:description" content="{escaped_desc}">
    <meta property="og:url" content="{canonical_url}">
    <meta property="og:type" content="website">
    <meta property="og:image" content="{CANONICAL_DOMAIN}/assets/images/hero-automation.jpg">
    <meta name="twitter:card" content="summary_large_image">

    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Plus+Jakarta+Sans:wght@700;800&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="/css/styles.css">

    <script type="application/ld+json">
    {cat_schema_json}
    </script>
    <style>
        :root {{
            --dg-navy: #081226;
            --dg-red: #9E1B32;
            --dg-red-hover: #b92a43;
            --dg-slate: #64748B;
            --dg-bg: #F8FAFC;
        }}
        body {{
            background-color: var(--dg-bg);
            font-family: 'Inter', sans-serif;
            color: #0F172A;
            margin: 0;
            padding: 0;
        }}
        .cat-hero {{
            background: linear-gradient(135deg, #081226 0%, #111E38 100%);
            color: #ffffff;
            padding: 60px 0 48px 0;
            text-align: center;
        }}
        .cat-hero h1 {{
            font-family: 'Plus Jakarta Sans', sans-serif;
            font-size: 32px;
            font-weight: 800;
            margin: 0 0 14px 0;
        }}
        .breadcrumbs-bar {{
            background: #ffffff;
            border-bottom: 1px solid #E2E8F0;
            padding: 12px 0;
            font-size: 13px;
        }}
        .breadcrumbs-bar a {{ color: var(--dg-slate); text-decoration: none; }}
        .breadcrumbs-bar a:hover {{ color: var(--dg-red); }}
        .breadcrumbs-bar span {{ color: #CBD5E1; margin: 0 8px; }}
        .breadcrumbs-bar strong {{ color: var(--dg-navy); }}
    </style>
</head>
<body>
    <header class="site-header">
        <div class="container nav-wrap">
            <a class="brand" href="/">
                <img src="/assets/images/logo-light.png" alt="DigiGarment Logo" style="height: 38px;">
            </a>
            <nav class="nav">
                <a href="/">Home</a>
                <a class="active" href="/jobs">Tiruppur Jobs</a>
                <a href="/tools">Tools</a>
                <a href="/services">Services</a>
                <a href="/blog">Blog</a>
                <a href="/#contact">Contact</a>
            </nav>
        </div>
    </header>

    <div class="breadcrumbs-bar">
        <div class="container">
            <a href="/">Home</a>
            <span>›</span>
            <a href="/jobs">Jobs</a>
            <span>›</span>
            <strong>{escaped_h1}</strong>
        </div>
    </div>

    <section class="cat-hero">
        <div class="container">
            <h1>{escaped_h1}</h1>
            <p style="color: #94A3B8; max-width: 650px; margin: 0 auto; line-height: 1.6;">{html.escape(cat_info['intro'])}</p>
        </div>
    </section>

    <main class="container" style="max-width: 900px; margin: 40px auto;">
        <h2 style="font-size: 20px; color: #081226; margin-bottom: 20px;">Current Openings in this Category</h2>
        {jobs_list_html}

        <div style="background: #ffffff; border: 1px solid #E2E8F0; border-radius: 12px; padding: 32px; margin-top: 40px;">
            <h2 style="font-size: 20px; color: #081226; margin-top: 0; margin-bottom: 16px;">Key Skills & Industry Responsibilities</h2>
            <div style="display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 24px;">
                {"".join(f'<span style="background: #F1F5F9; color: #081226; padding: 6px 14px; border-radius: 20px; font-size: 13px; font-weight: 500;">{html.escape(s)}</span>' for s in cat_info["skills"])}
            </div>

            <h2 style="font-size: 20px; color: #081226; margin-top: 32px; margin-bottom: 16px;">Category FAQ</h2>
            {faq_html}
        </div>
    </main>

    <footer style="background: #081226; color: #94A3B8; padding: 40px 0 20px 0; text-align: center; font-size: 14px; margin-top: 48px;">
        <p style="margin-bottom: 12px;">© 2026 DigiGarment. Verified Garment Industry Career Platform.</p>
        <div>
            <a href="/" style="color: #94A3B8; margin: 0 10px; text-decoration: none;">Home</a>
            <a href="/jobs" style="color: #94A3B8; margin: 0 10px; text-decoration: none;">All Jobs</a>
            <a href="/tools/sam-calculator" style="color: #94A3B8; margin: 0 10px; text-decoration: none;">SAM Calculator</a>
            <a href="/services" style="color: #94A3B8; margin: 0 10px; text-decoration: none;">Services</a>
            <a href="/blog" style="color: #94A3B8; margin: 0 10px; text-decoration: none;">Blog</a>
        </div>
    </footer>
</body>
</html>
"""

    # 2. Check if slug maps to a REAL Job record in the database
    if not db_helpers["db_enabled"] or not db_helpers["query_db"]:
        # When DB is offline, return jobs.html gracefully
        return FileResponse(os.path.join(BASE_DIR, "jobs.html"))

    try:
        query = """
            SELECT j.id, j.title, j.slug, j.department, j.job_role, j.job_type,
                   j.location, j.openings_count, j.experience_min, j.experience_max,
                   j.salary_min, j.salary_max, j.salary_text, j.description,
                   j.requirements, j.skills, j.qualification, j.gender,
                   j.contact_phone, j.contact_whatsapp, j.contact_email, j.application_url,
                   j.published_at, j.created_at,
                   COALESCE(cp.company_name, c.name, '') AS company_name,
                   COALESCE(cp.company_logo, c.logo_url, '') AS company_logo,
                   COALESCE(cp.location, c.location, j.location) AS company_location
            FROM jobs j
            LEFT JOIN companies c ON j.company_id = c.id
            LEFT JOIN company_profiles cp ON j.company_profile_id = cp.id
            WHERE (j.slug = %s OR CAST(j.id AS VARCHAR) = %s)
              AND LOWER(j.status) = 'published'
              AND COALESCE(j.is_archived, FALSE) = FALSE;
        """
        rows = db_helpers["query_db"](query, (str(slug), str(slug)))
        if not rows:
            # Job not found or archived
            raise HTTPException(status_code=404, detail="Job posting not found or no longer active.")

        job = rows[0]
        job_title = job.get("title") or "Garment Job Vacancy"
        job_slug = job.get("slug") or str(job.get("id"))
        canonical_url = f"{CANONICAL_DOMAIN}/jobs/{job_slug}"
        job_loc = job.get("location") or "Tiruppur, Tamil Nadu, India"
        job_comp = job.get("company_name") or "Garment Manufacturing Unit"
        job_desc = job.get("description") or "Garment manufacturing vacancy in Tiruppur."
        job_type = job.get("job_type") or "FULL_TIME"
        if job_type.lower() in ("full time", "full-time", "full_time"):
            schema_job_type = "FULL_TIME"
        elif job_type.lower() in ("part time", "part-time", "part_time"):
            schema_job_type = "PART_TIME"
        elif job_type.lower() in ("contract", "contractual"):
            schema_job_type = "CONTRACTOR"
        else:
            schema_job_type = "FULL_TIME"

        pub_date = job.get("published_at") or job.get("created_at")
        date_posted_iso = pub_date.strftime("%Y-%m-%d") if isinstance(pub_date, (datetime.datetime, datetime.date)) else datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")

        # Build JobPosting JSON-LD strictly from genuine database fields (omitting missing values)
        job_posting_dict: Dict[str, Any] = {
            "@context": "https://schema.org",
            "@type": "JobPosting",
            "title": job_title,
            "description": html.escape(job_desc),
            "datePosted": date_posted_iso,
            "employmentType": schema_job_type,
            "hiringOrganization": {
                "@type": "Organization",
                "name": job_comp
            },
            "jobLocation": {
                "@type": "Place",
                "address": {
                    "@type": "PostalAddress",
                    "addressLocality": "Tiruppur",
                    "addressRegion": "Tamil Nadu",
                    "addressCountry": "IN"
                }
            }
        }

        # Only add salary if genuinely provided in database
        if job.get("salary_min") and job.get("salary_max"):
            job_posting_dict["baseSalary"] = {
                "@type": "MonetaryAmount",
                "currency": "INR",
                "value": {
                    "@type": "QuantitativeValue",
                    "minValue": float(job["salary_min"]),
                    "maxValue": float(job["salary_max"]),
                    "unitText": "MONTH"
                }
            }
        elif job.get("salary_min"):
            job_posting_dict["baseSalary"] = {
                "@type": "MonetaryAmount",
                "currency": "INR",
                "value": {
                    "@type": "QuantitativeValue",
                    "value": float(job["salary_min"]),
                    "unitText": "MONTH"
                }
            }

        if job.get("experience_min") is not None:
            job_posting_dict["experienceRequirements"] = {
                "@type": "OccupationalExperienceRequirements",
                "monthsOfExperience": int(job["experience_min"]) * 12
            }

        import json
        structured_data_json = json.dumps({
            "@context": "https://schema.org",
            "@graph": [
                job_posting_dict,
                {
                    "@type": "BreadcrumbList",
                    "itemListElement": [
                        {"@type": "ListItem", "position": 1, "name": "Home", "item": f"{CANONICAL_DOMAIN}/"},
                        {"@type": "ListItem", "position": 2, "name": "Jobs", "item": f"{CANONICAL_DOMAIN}/jobs"},
                        {"@type": "ListItem", "position": 3, "name": job_title, "item": canonical_url}
                    ]
                }
            ]
        })

        meta_page_title = f"{job_title} | Tiruppur Garment Jobs"
        meta_page_desc = f"Apply for {job_title} at {job_comp} in {job_loc}. Verified garment vacancy on DigiGarment."

        # Read jobs.html to serve complete progressive frontend application
        with open(os.path.join(BASE_DIR, "jobs.html"), "r", encoding="utf-8") as f:
            html_template = f.read()

        # Inject dynamic SEO tags & schema into jobs.html
        injected_head = f"""
    <title>{html.escape(meta_page_title)}</title>
    <meta name="description" content="{html.escape(meta_page_desc)}">
    <link rel="canonical" href="{canonical_url}">
    <meta property="og:title" content="{html.escape(meta_page_title)}">
    <meta property="og:description" content="{html.escape(meta_page_desc)}">
    <meta property="og:url" content="{canonical_url}">
    <meta property="og:type" content="article">
    <meta property="og:image" content="{CANONICAL_DOMAIN}/assets/images/hero-automation.jpg">
    <meta name="twitter:card" content="summary_large_image">
    <script type="application/ld+json">
    {structured_data_json}
    </script>
        """

        # Replace standard title and metadata with real dynamic job metadata
        pattern = r'<title>.*?</title>'
        custom_html = re.sub(pattern, injected_head, html_template, count=1)

        # Inject auto-open script for client-side modal on load
        script_injection = f"""
        <script>
            window.addEventListener('DOMContentLoaded', () => {{
                if (typeof openJobModalBySlug === 'function') {{
                    openJobModalBySlug("{job_slug}");
                }}
            }});
        </script>
        </body>
        """
        custom_html = custom_html.replace("</body>", script_injection)

        return HTMLResponse(content=custom_html)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error rendering job detail page {slug}: {e}")
        return FileResponse(os.path.join(BASE_DIR, "jobs.html"))
