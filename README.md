# Tirupur Garments — Website Foundation & Architecture

A production-ready web application for **Tirupur Garments**, a digital platform for the Tirupur garment and apparel manufacturing industry cluster. Built using Python, Flask, and SQLAlchemy, designed for future React frontend integration and AI automation.

## Project Architecture

The codebase follows a modular blueprint layout:

```text
tirupur-garments/
├── app/
│   ├── __init__.py           # Application Factory, Extension Init
│   ├── models/               # Modular SQLAlchemy Database Models
│   │   ├── __init__.py
│   │   ├── user.py
│   │   ├── news.py
│   │   ├── knowledge.py
│   │   ├── job.py
│   │   ├── company.py
│   │   ├── service.py
│   │   ├── tool.py
│   │   ├── media.py
│   │   └── contact.py
│   ├── routes/               # Modular Blueprint Routes
│   │   ├── __init__.py
│   │   ├── web.py            # Serves HTML Templates & Crawler SEO routes
│   │   ├── api.py            # Future-proof JSON REST API Endpoints
│   │   └── admin.py          # Admin UI Dashboard Endpoints
│   ├── templates/            # Jinja2 Layout Templates
│   │   ├── base.html         # Base header, footer and SEO parameters
│   │   ├── index.html        # Homepage with content feeds
│   │   ├── news.html         # News articles list and reader
│   │   ├── knowledge.html    # Knowledge Base guides list and reader
│   │   ├── jobs.html         # Recruitment listings and descriptions
│   │   ├── companies.html    # Manufacturer and supplier directories
│   │   ├── services.html     # Industrial services profiles
│   │   ├── tools.html        # Interactive calculators index
│   │   ├── tool_detail.html  # Dynamic forms (SAM & GSM)
│   │   ├── ai_studio.html    # Chat interface mock assistant
│   │   └── sitemap_xml.html  # XML format sitemap layout
│   └── static/               # Assets
│       ├── css/
│       │   └── styles.css    # Responsive Mobile-First CSS with CSS variables
│       └── js/
│           ├── main.js       # Responsive nav drawer and form handlers
│           └── tools/
│               ├── sam.js    # SAM Calculator inputs and logic
│               └── gsm.js    # Fabric GSM Calculator inputs and logic
├── migrations/               # Alembic/Flask-Migrate Schema Versions
├── config.py                 # Enforces config & environment validation
├── run.py                    # Application Entrypoint
├── seed.py                   # Populates development mock items
├── requirements.txt          # PIP dependencies
├── .env.example              # Sample environment template
└── README.md                 # Project documentation
```

---

## Getting Started

### 1. Prerequisite Setup

Ensure Python is installed on your machine.

Clone/copy the workspace project folder to your local directory.

### 2. Establish Virtual Environment

Create and activate a python virtual environment:

**On Windows (PowerShell):**
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

**On macOS/Linux:**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install packages:
```bash
pip install -r requirements.txt
```

### 3. Environment Variables Configuration

Copy `.env.example` to `.env` in the root folder:

```bash
cp .env.example .env
```

Configure your **Supabase PostgreSQL Connection String** inside the `.env` file:
```text
DATABASE_URL=postgresql://postgres:[YOUR-PASSWORD]@[YOUR-SUPABASE-HOST]:5432/postgres
SECRET_KEY=enter-a-secure-random-cryptographic-key-here
```

*Note: The application checks for the presence of `DATABASE_URL` on boot and will raise a `RuntimeError` immediately if it is missing, refusing to start on SQLite.*

### 4. Database Migrations (Alembic)

Initialize and configure the PostgreSQL tables:

```bash
# Initialize migration repository (run only once, already done for this project base)
flask db init

# Inspect and generate schema scripts
flask db migrate -m "initial migration"

# Apply changes to your Supabase PostgreSQL Database
flask db upgrade
```

### 5. Seed Mock Data

Populate categories, initial news, sample jobs, manufacturers, and calculators for testing:

```bash
python seed.py
```

### 6. Run the Application

```bash
python run.py
```

Open your browser and navigate to `http://localhost:5000`.

---

## Features & Verification Endpoints

### SEO & Public Routing (Clean URLs)
- Homepage: `/`
- Garment Hub News: `/news` & `/news/<slug>`
- Knowledge Guides: `/knowledge` & `/knowledge/<slug>`
- Job Openings: `/jobs` & `/jobs/<slug>`
- Company profiles: `/companies` & `/companies/<slug>`
- Industrial services: `/services` & `/services/<slug>`
- Calculators directory: `/tools`
- SAM Calculator: `/tools/sam-calculator`
- Fabric GSM Calculator: `/tools/fabric-gsm-calculator`
- Garment AI Studio: `/ai-studio`
- XML Sitemap: `/sitemap.xml` (Dynamically crawlable list of published content)
- Crawler Directives: `/robots.txt`

### REST API Endpoints (Future React Compatibility)
- `GET /api/news` - Lists articles
- `GET /api/news/<slug>` - Single article Details
- `GET /api/knowledge` - Lists guides
- `GET /api/knowledge/<slug>` - Single guide Details
- `GET /api/jobs` - Lists jobs
- `GET /api/companies` - Lists companies
- `GET /api/services` - Lists services
- `GET /api/tools` - Lists tools
- `POST /api/contact` - Submits a contact inquiry

### Admin Section
- Route: `/admin` - View site statistics and read contact inquiries database.
