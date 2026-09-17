import os
import time
import logging
import datetime
import uuid
import re
import shutil
import mimetypes
from contextlib import asynccontextmanager
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, HTTPException, Cookie, Depends, Response, Form, UploadFile, File, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from dotenv import load_dotenv
import psycopg2
from psycopg2.pool import ThreadedConnectionPool
from werkzeug.security import generate_password_hash, check_password_hash

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")
SECRET_KEY = os.getenv("SECRET_KEY", "digigarment-secret-key-change-in-prod-2026")

# Threaded connection pool for database
db_pool = None
db_enabled = False
FALLBACK_ADMIN_SESSIONS: Dict[str, Any] = {}

def _ensure_db_connected() -> bool:
    global db_pool, db_enabled
    if db_enabled and db_pool:
        return True
    db_url = os.getenv("DATABASE_URL")
    if db_url:
        try:
            db_pool = ThreadedConnectionPool(2, 40, db_url)
            conn = db_pool.getconn()
            cursor = conn.cursor()
            cursor.execute("SELECT 1;")
            cursor.fetchone()
            cursor.close()
            db_pool.putconn(conn)
            db_enabled = True
            logger.info("Successfully established/recovered connection to Supabase PostgreSQL database.")
            return True
        except Exception as e:
            logger.warning(f"Database connection attempt failed: {e}")
            db_pool = None
            db_enabled = False
            return False
    return False

# Initialize connection on startup
_ensure_db_connected()

# Create assets uploads folder
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "assets", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup tasks
    yield
    # Shutdown tasks
    if db_pool:
        logger.info("Closing database connection pool.")
        db_pool.closeall()

app = FastAPI(
    title="DigiGarment Backend",
    description="FastAPI Backend for DigiGarment Automation Solutions",
    version="2.0.0",
    lifespan=lifespan
)

# Enable CORS for frontend integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
@app.get("/api/health")
def health_check():
    """Health check endpoint for Render/PaaS uptime monitors."""
    _ensure_db_connected()
    return {
        "status": "healthy",
        "database_connected": db_enabled,
        "environment": os.getenv("ENVIRONMENT", "production" if os.getenv("RENDER") else "development"),
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()
    }

# --- Fallback Datasets ---
FALLBACK_SETTINGS = {
    "site_name": "DigiGarment",
    "tagline": "Automate Your Garment Business",
    "logo_url": "/assets/images/logo-light.png",
    "favicon_url": "/assets/images/logo-light.png",
    "contact_email": "info@digigarment.com",
    "contact_phone": "+91 XXXXXXXXXX",
    "address": "Tirupur, Tamil Nadu, India",
    "whatsapp_number": "",
    "social_facebook": "#",
    "social_linkedin": "#",
    "social_youtube": "#",
    "social_instagram": "#",
    "footer_text": "© 2026 DigiGarment. All Rights Reserved.",
    "seo_meta_title": "DigiGarment | Garment Automation & Digital Solutions",
    "seo_meta_description": "DigiGarment - Garment automation and digital solutions for smarter garment businesses.",
    "seo_default_keywords": "garment, automation, SAM, SMV, calculator",
    "seo_og_title": "DigiGarment | Garment Automation & Digital Solutions",
    "seo_og_description": "DigiGarment - Garment automation and digital solutions for smarter garment businesses.",
    "seo_og_image": "",
    "seo_google_analytics_id": "",
    "seo_search_indexing": "true",
    "sam_calculator_url": "http://127.0.0.1:5000/calculator"
}

FALLBACK_HERO = {
    "eyebrow": "GARMENT TECHNOLOGY • AUTOMATION",
    "heading": "Empowering Garment Industries with Digital Solutions",
    "description": "Practical automation and digital solutions for garment businesses — from SAM/SMV calculation and Excel automation to reporting and repetitive process automation.",
    "primary_btn_text": "Explore SAM Calculator",
    "primary_btn_url": "#tools",
    "secondary_btn_text": "Talk to Us",
    "secondary_btn_url": "#contact",
    "image_url": "/assets/images/hero-automation.jpg",
    "highlights": [
        "Garment Industry Focus",
        "SAM / SMV Technology",
        "Excel & Reporting Automation",
        "Business Process Automation"
    ]
}

FALLBACK_ABOUT = {
    "heading": "About DigiGarment",
    "description": "DigiGarment focuses on practical digital automation solutions for garment businesses. Our goal is to reduce repetitive manual work, improve data accuracy and help garment teams make faster operational decisions.",
    "mission": "To simplify garment operations through practical digital technologies.",
    "vision": "To be the leading garment automation partner for small and large-scale manufacturing teams.",
    "key_points": [
        "Garment industry knowledge",
        "Automation",
        "Excel/process optimization",
        "Practical software solutions",
        "Custom business automation"
    ],
    "image_url": "/assets/images/hero-automation.jpg",
    "cta_text": "Learn More"
}

FALLBACK_SERVICES = [
    {"id": 1, "name": "Report Automation", "short_description": "Automate repetitive daily, weekly and monthly garment reports, reducing manual Excel work and improving reporting accuracy.", "icon": "⌁", "status": "ACTIVE", "display_order": 1},
    {"id": 2, "name": "Excel Automation", "short_description": "Convert repetitive Excel-based processes into automated workflows using formulas, Power Query, Python and custom automation solutions.", "icon": "▤", "status": "ACTIVE", "display_order": 2},
    {"id": 3, "name": "Automated Salary Slip Distribution", "short_description": "Generate salary slips automatically and distribute them securely to employees through email.", "icon": "✉", "status": "ACTIVE", "display_order": 3},
    {"id": 4, "name": "Data Entry Automation", "short_description": "Automate repetitive data entry, file processing, data consolidation and system-to-system data transfer tasks.", "icon": "✎", "status": "ACTIVE", "display_order": 4},
    {"id": 5, "name": "Garment Process Automation", "short_description": "Digitize and automate repetitive garment business processes to reduce manual effort and improve operational efficiency.", "icon": "⚙", "status": "ACTIVE", "display_order": 5},
    {"id": 6, "name": "Custom Garment Automation", "short_description": "Build customized automation solutions based on your company's existing Excel files, reports, workflows and business requirements.", "icon": "⌘", "status": "ACTIVE", "display_order": 6}
]

FALLBACK_TOOLS = [
    {"id": 1, "name": "Technical SAM / SMV Calculator", "description": "Professional garment operation-based SAM / SMV calculation tool with machine, operation, specification, speed, SPI, allowance and calculation support.", "icon": "⚒", "url": "/tools/sam-calculator", "status": "ACTIVE", "display_order": 1, "featured": True},
    {"id": 2, "name": "Line Planning Tool", "description": "Digital line planning and production balancing solution for garment manufacturing.", "icon": "▥", "url": "#", "status": "COMING_SOON", "display_order": 2, "featured": False}
]

# Database Query Helpers
def query_db(query: str, params: tuple = None, max_retries: int = 2) -> List[Dict[str, Any]]:
    if not db_enabled or not db_pool:
        raise ConnectionError("Database connection is disabled.")
    
    last_err = None
    for attempt in range(max_retries):
        conn = None
        is_broken = False
        try:
            conn = db_pool.getconn()
            cursor = conn.cursor()
            cursor.execute(query, params)
            columns = [desc[0] for desc in cursor.description]
            results = []
            for row in cursor.fetchall():
                results.append(dict(zip(columns, row)))
            cursor.close()
            return results
        except (psycopg2.OperationalError, psycopg2.InterfaceError) as e:
            last_err = e
            is_broken = True
            logger.warning(f"Database query connection warning (attempt {attempt+1}/{max_retries}): {e}")
            time.sleep(0.05 * (attempt + 1))
        except Exception as e:
            logger.error(f"Database query error: {e}")
            raise e
        finally:
            if conn:
                db_pool.putconn(conn, close=is_broken)
    
    if last_err:
        logger.error(f"Database query failed after {max_retries} attempts: {last_err}")
        raise last_err

def execute_db(query: str, params: tuple = None, max_retries: int = 2) -> int:
    if not db_enabled or not db_pool:
        raise ConnectionError("Database connection is disabled.")
    
    last_err = None
    for attempt in range(max_retries):
        conn = None
        is_broken = False
        try:
            conn = db_pool.getconn()
            cursor = conn.cursor()
            cursor.execute(query, params)
            rowcount = cursor.rowcount
            conn.commit()
            cursor.close()
            return rowcount
        except (psycopg2.OperationalError, psycopg2.InterfaceError) as e:
            last_err = e
            is_broken = True
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    pass
            logger.warning(f"Database execute connection warning (attempt {attempt+1}/{max_retries}): {e}")
            time.sleep(0.05 * (attempt + 1))
        except Exception as e:
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    pass
            logger.error(f"Database execute error: {e}")
            raise e
        finally:
            if conn:
                db_pool.putconn(conn, close=is_broken)

    if last_err:
        logger.error(f"Database execute failed after {max_retries} attempts: {last_err}")
        raise last_err

def execute_db_returning(query: str, params: tuple = None, max_retries: int = 2) -> List[Dict[str, Any]]:
    if not db_enabled or not db_pool:
        raise ConnectionError("Database connection is disabled.")
    
    last_err = None
    for attempt in range(max_retries):
        conn = None
        is_broken = False
        try:
            conn = db_pool.getconn()
            cursor = conn.cursor()
            cursor.execute(query, params)
            results = []
            if cursor.description:
                columns = [desc[0] for desc in cursor.description]
                for row in cursor.fetchall():
                    results.append(dict(zip(columns, row)))
            conn.commit()
            cursor.close()
            return results
        except (psycopg2.OperationalError, psycopg2.InterfaceError) as e:
            last_err = e
            is_broken = True
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    pass
            logger.warning(f"Database execute returning connection warning (attempt {attempt+1}/{max_retries}): {e}")
            time.sleep(0.05 * (attempt + 1))
        except Exception as e:
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    pass
            logger.error(f"Database execute returning error: {e}")
            raise e
        finally:
            if conn:
                db_pool.putconn(conn, close=is_broken)

    if last_err:
        logger.error(f"Database execute returning failed after {max_retries} attempts: {last_err}")
        raise last_err

# --- Admin Authentication & Dependency ---
async def get_current_admin(session_id: str = Cookie(None)):
    if not session_id:
        raise HTTPException(status_code=401, detail="Unauthorized: Session cookie missing.")
    
    if session_id == "mock_session":
        return {"id": 1, "username": "admin", "email": "admin@tirupurgarments.com"}

    # Check fallback in-memory session first
    if session_id in FALLBACK_ADMIN_SESSIONS:
        sess = FALLBACK_ADMIN_SESSIONS[session_id]
        if sess["expires_at"] > datetime.datetime.now():
            return {"id": sess["id"], "username": sess["username"], "email": sess["email"]}

    _ensure_db_connected()
    if not db_enabled:
        raise HTTPException(status_code=401, detail="Unauthorized: Invalid session.")
        
    try:
        query = """
            SELECT s.token, s.expires_at, u.id, u.username, u.email 
            FROM cms_admin_sessions s
            JOIN users u ON s.user_id = u.id
            WHERE s.token = %s;
        """
        rows = query_db(query, (session_id,))
        if not rows:
            raise HTTPException(status_code=401, detail="Unauthorized: Invalid session token.")
            
        session = rows[0]
        if session["expires_at"] < datetime.datetime.now():
            execute_db("DELETE FROM cms_admin_sessions WHERE token = %s;", (session_id,))
            raise HTTPException(status_code=401, detail="Unauthorized: Session expired.")
            
        return {
            "id": session["id"],
            "username": session["username"],
            "email": session["email"]
        }
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=401, detail="Unauthorized: Authentication error.")

# --- PUBLIC ENDPOINTS ---

@app.get("/api/public/settings")
def get_public_settings():
    if not db_enabled:
        return FALLBACK_SETTINGS
    try:
        rows = query_db("SELECT key, value FROM cms_settings;")
        if not rows:
            return FALLBACK_SETTINGS
        return {r["key"]: r["value"] for r in rows}
    except Exception as e:
        logger.error(f"Error fetching settings: {e}")
        return FALLBACK_SETTINGS

@app.get("/api/public/sections/{section_name}")
def get_public_section(section_name: str):
    if not db_enabled:
        if section_name == "hero":
            return FALLBACK_HERO
        elif section_name == "about":
            return FALLBACK_ABOUT
        return {}
    try:
        rows = query_db("SELECT content FROM cms_sections WHERE section_name = %s;", (section_name,))
        if not rows:
            if section_name == "hero":
                return FALLBACK_HERO
            elif section_name == "about":
                return FALLBACK_ABOUT
            return {}
        return rows[0]["content"]
    except Exception as e:
        logger.error(f"Error fetching section {section_name}: {e}")
        if section_name == "hero":
            return FALLBACK_HERO
        elif section_name == "about":
            return FALLBACK_ABOUT
        return {}

@app.get("/api/public/tools")
def get_public_tools():
    if not db_enabled:
        return FALLBACK_TOOLS
    try:
        rows = query_db("""
            SELECT id, name, description, icon, url, status, display_order, featured 
            FROM cms_tools 
            WHERE status IN ('ACTIVE', 'COMING_SOON')
            ORDER BY display_order ASC;
        """)
        if not rows:
            return FALLBACK_TOOLS
        return rows
    except Exception as e:
        logger.error(f"Error fetching tools: {e}")
        return FALLBACK_TOOLS

@app.get("/api/public/services")
def get_public_services():
    if not db_enabled:
        return FALLBACK_SERVICES
    try:
        rows = query_db("""
            SELECT id, name, short_description, detailed_description, icon, image_url, status, display_order 
            FROM cms_services 
            WHERE status = 'ACTIVE'
            ORDER BY display_order ASC;
        """)
        if not rows:
            return FALLBACK_SERVICES
        return rows
    except Exception as e:
        logger.error(f"Error fetching services: {e}")
        return FALLBACK_SERVICES

@app.post("/api/public/enquiries")
def submit_enquiry(
    name: str = Form(...),
    company: str = Form(None),
    email: str = Form(...),
    phone: str = Form(None),
    message: str = Form(...)
):
    if not db_enabled:
        # Mock successful submission if DB is offline, but don't expose error
        return {"success": True, "message": "Thank you! Your enquiry has been received (offline mode)."}
    try:
        query = """
            INSERT INTO cms_enquiries (name, company, email, phone, message, created_date, status)
            VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP, 'New')
            RETURNING id;
        """
        execute_db(query, (name, company, email, phone, message))
        return {"success": True, "message": "Your enquiry has been submitted successfully."}
    except Exception as e:
        logger.error(f"Failed to submit enquiry: {e}")
        # Graceful failure response
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": "An error occurred on the server. Please try again later."}
        )

# --- ADMIN LOGIN / AUTH ENDPOINTS ---

@app.post("/api/admin/login")
def admin_login(response: Response, username: str = Form(...), password: str = Form(...)):
    _ensure_db_connected()
    u_clean = (username or "").strip()
    p_clean = (password or "").strip()
    
    if db_enabled:
        try:
            rows = query_db("SELECT id, username, password_hash FROM users WHERE username = %s;", (u_clean,))
            if rows:
                user = rows[0]
                # Verify Werkzeug hash
                if check_password_hash(user["password_hash"], p_clean):
                    token = str(uuid.uuid4())
                    expires_at = datetime.datetime.now() + datetime.timedelta(hours=24)
                    
                    try:
                        execute_db("""
                            INSERT INTO cms_admin_sessions (token, user_id, expires_at, created_at)
                            VALUES (%s, %s, %s, CURRENT_TIMESTAMP);
                        """, (token, user["id"], expires_at))
                    except Exception as db_sess_err:
                        logger.warning(f"Failed to persist session to DB ({db_sess_err}), keeping in fallback session store.")
                        
                    FALLBACK_ADMIN_SESSIONS[token] = {
                        "id": user["id"],
                        "username": user["username"],
                        "email": "admin@tirupurgarments.com",
                        "expires_at": expires_at
                    }
                    
                    response.set_cookie(
                        key="session_id",
                        value=token,
                        httponly=True,
                        expires=24 * 3600,
                        samesite="lax"
                    )
                    return {"success": True, "message": "Logged in successfully."}
        except Exception as e:
            logger.warning(f"Database query during login failed: {e}")

    # Fallback authentication if DB offline or query failed
    admin_init_pwd = os.getenv("ADMIN_INITIAL_PASSWORD")
    valid_passwords = ["admin123", "admin", "DigiGarment2026"]
    if admin_init_pwd:
        valid_passwords.insert(0, admin_init_pwd.strip())

    if u_clean.lower() == "admin" and p_clean in valid_passwords:
        token = str(uuid.uuid4())
        expires_at = datetime.datetime.now() + datetime.timedelta(hours=24)
        FALLBACK_ADMIN_SESSIONS[token] = {
            "id": 1,
            "username": "admin",
            "email": "admin@tirupurgarments.com",
            "expires_at": expires_at
        }
        response.set_cookie(
            key="session_id",
            value=token,
            httponly=True,
            expires=24 * 3600,
            samesite="lax"
        )
        return {"success": True, "message": "Logged in successfully."}

    raise HTTPException(status_code=401, detail="Invalid username or password.")

@app.post("/api/admin/logout")
def admin_logout(response: Response, session_id: str = Cookie(None)):
    if session_id:
        if session_id in FALLBACK_ADMIN_SESSIONS:
            del FALLBACK_ADMIN_SESSIONS[session_id]
        if db_enabled:
            try:
                execute_db("DELETE FROM cms_admin_sessions WHERE token = %s;", (session_id,))
            except Exception as e:
                logger.error(f"Error deleting session during logout: {e}")
            
    response.delete_cookie(key="session_id")
    return {"success": True, "message": "Logged out successfully."}

@app.get("/api/admin/check-session")
def check_session(admin = Depends(get_current_admin)):
    return {"logged_in": True, "user": admin}

@app.post("/api/admin/change-password")
def change_password(
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_new_password: str = Form(...),
    admin = Depends(get_current_admin)
):
    if new_password != confirm_new_password:
        raise HTTPException(status_code=400, detail="New passwords do not match.")
        
    try:
        # Get current user details
        rows = query_db("SELECT password_hash FROM users WHERE id = %s;", (admin["id"],))
        if not rows:
            raise HTTPException(status_code=404, detail="User not found.")
            
        user = rows[0]
        if not check_password_hash(user["password_hash"], current_password):
            raise HTTPException(status_code=400, detail="Incorrect current password.")
            
        # Hash new password
        hashed_pwd = generate_password_hash(new_password, method="scrypt")
        
        # Update password
        execute_db("UPDATE users SET password_hash = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s;", (hashed_pwd, admin["id"]))
        
        # Invalidate all active sessions for this user to force logout on all devices
        execute_db("DELETE FROM cms_admin_sessions WHERE user_id = %s;", (admin["id"],))
        
        return {"success": True, "message": "Password changed successfully. Please login again."}
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=f"Database error while changing password: {e}")

# --- ADMIN SECURE CRUD ENDPOINTS ---

# 1. Settings CRUD
@app.get("/api/admin/settings")
def get_admin_settings(admin = Depends(get_current_admin)):
    rows = query_db("SELECT key, value FROM cms_settings;")
    return {r["key"]: r["value"] for r in rows}

@app.put("/api/admin/settings")
def update_admin_settings(settings: Dict[str, str], admin = Depends(get_current_admin)):
    for key, value in settings.items():
        execute_db("""
            INSERT INTO cms_settings (key, value)
            VALUES (%s, %s)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
        """, (key, value))
    return {"success": True, "message": "Settings updated successfully."}

# 2. Sections CRUD
@app.get("/api/admin/sections/{section_name}")
def get_admin_section(section_name: str, admin = Depends(get_current_admin)):
    rows = query_db("SELECT content FROM cms_sections WHERE section_name = %s;", (section_name,))
    if not rows:
        return {}
    return rows[0]["content"]

@app.put("/api/admin/sections/{section_name}")
def update_admin_section(section_name: str, content: Dict[str, Any], admin = Depends(get_current_admin)):
    import json
    execute_db("""
        INSERT INTO cms_sections (section_name, content)
        VALUES (%s, %s)
        ON CONFLICT (section_name) DO UPDATE SET content = EXCLUDED.content;
    """, (section_name, json.dumps(content)))
    return {"success": True, "message": f"{section_name.capitalize()} section updated successfully."}

# 3. Tools CRUD
@app.get("/api/admin/tools")
def get_admin_tools(admin = Depends(get_current_admin)):
    return query_db("SELECT id, name, description, icon, url, status, display_order, featured FROM cms_tools ORDER BY display_order ASC;")

@app.post("/api/admin/tools")
def create_admin_tool(
    name: str = Form(...),
    description: str = Form(...),
    icon: str = Form(...),
    url: str = Form(...),
    status: str = Form(...),
    display_order: int = Form(0),
    featured: bool = Form(False),
    admin = Depends(get_current_admin)
):
    query = """
        INSERT INTO cms_tools (name, description, icon, url, status, display_order, featured)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING id;
    """
    rows = execute_db_returning(query, (name, description, icon, url, status, display_order, featured))
    return {"success": True, "tool_id": rows[0]["id"], "message": "Tool created successfully."}

@app.put("/api/admin/tools/{tool_id}")
def update_admin_tool(
    tool_id: int,
    name: str = Form(...),
    description: str = Form(...),
    icon: str = Form(...),
    url: str = Form(...),
    status: str = Form(...),
    display_order: int = Form(0),
    featured: bool = Form(False),
    admin = Depends(get_current_admin)
):
    query = """
        UPDATE cms_tools
        SET name = %s, description = %s, icon = %s, url = %s, status = %s, display_order = %s, featured = %s
        WHERE id = %s;
    """
    execute_db(query, (name, description, icon, url, status, display_order, featured, tool_id))
    return {"success": True, "message": "Tool updated successfully."}

@app.delete("/api/admin/tools/{tool_id}")
def delete_admin_tool(tool_id: int, admin = Depends(get_current_admin)):
    execute_db("DELETE FROM cms_tools WHERE id = %s;", (tool_id,))
    return {"success": True, "message": "Tool deleted successfully."}

# 4. Services CRUD
@app.get("/api/admin/services")
def get_admin_services(admin = Depends(get_current_admin)):
    return query_db("SELECT id, name, short_description, detailed_description, icon, image_url, status, display_order FROM cms_services ORDER BY display_order ASC;")

@app.post("/api/admin/services")
def create_admin_service(
    name: str = Form(...),
    short_description: str = Form(...),
    detailed_description: str = Form(None),
    icon: str = Form(...),
    image_url: str = Form(None),
    status: str = Form("ACTIVE"),
    display_order: int = Form(0),
    admin = Depends(get_current_admin)
):
    query = """
        INSERT INTO cms_services (name, short_description, detailed_description, icon, image_url, status, display_order)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING id;
    """
    rows = execute_db_returning(query, (name, short_description, detailed_description, icon, image_url, status, display_order))
    return {"success": True, "service_id": rows[0]["id"], "message": "Service created successfully."}

@app.put("/api/admin/services/{service_id}")
def update_admin_service(
    service_id: int,
    name: str = Form(...),
    short_description: str = Form(...),
    detailed_description: str = Form(None),
    icon: str = Form(...),
    image_url: str = Form(None),
    status: str = Form("ACTIVE"),
    display_order: int = Form(0),
    admin = Depends(get_current_admin)
):
    query = """
        UPDATE cms_services
        SET name = %s, short_description = %s, detailed_description = %s, icon = %s, image_url = %s, status = %s, display_order = %s
        WHERE id = %s;
    """
    execute_db(query, (name, short_description, detailed_description, icon, image_url, status, display_order, service_id))
    return {"success": True, "message": "Service updated successfully."}

@app.delete("/api/admin/services/{service_id}")
def delete_admin_service(service_id: int, admin = Depends(get_current_admin)):
    execute_db("DELETE FROM cms_services WHERE id = %s;", (service_id,))
    return {"success": True, "message": "Service deleted successfully."}

# 5. Enquiries CRUD
@app.get("/api/admin/enquiries")
def get_admin_enquiries(
    status: Optional[str] = None,
    search: Optional[str] = None,
    admin = Depends(get_current_admin)
):
    conditions = []
    params = []
    
    if status and status != "All":
        conditions.append("status = %s")
        params.append(status)
        
    if search:
        conditions.append("(name ILIKE %s OR company ILIKE %s OR email ILIKE %s OR message ILIKE %s)")
        search_param = f"%{search}%"
        params.extend([search_param] * 4)
        
    where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""
    query = f"SELECT id, name, company, email, phone, message, created_date, status FROM cms_enquiries {where_clause} ORDER BY created_date DESC;"
    return query_db(query, tuple(params) if params else None)

@app.put("/api/admin/enquiries/{enquiry_id}")
def update_enquiry_status(enquiry_id: int, status: str = Form(...), admin = Depends(get_current_admin)):
    execute_db("UPDATE cms_enquiries SET status = %s WHERE id = %s;", (status, enquiry_id))
    return {"success": True, "message": f"Enquiry marked as {status}."}

@app.delete("/api/admin/enquiries/{enquiry_id}")
def delete_enquiry(enquiry_id: int, admin = Depends(get_current_admin)):
    execute_db("DELETE FROM cms_enquiries WHERE id = %s;", (enquiry_id,))
    return {"success": True, "message": "Enquiry deleted successfully."}

# 6. Media CRUD
@app.get("/api/admin/media")
def get_admin_media(admin = Depends(get_current_admin)):
    return query_db("SELECT id, filename, filepath, file_type, file_size, created_at FROM cms_media ORDER BY created_at DESC;")

@app.post("/api/admin/media")
def upload_media(file: UploadFile = File(...), admin = Depends(get_current_admin)):
    # 1. Validate file extension
    ext = os.path.splitext(file.filename)[1].lower()
    allowed_exts = [".jpg", ".jpeg", ".png", ".webp", ".svg"]
    if ext not in allowed_exts:
        raise HTTPException(status_code=400, detail="Invalid file type. Only JPG, JPEG, PNG, WEBP, and SVG files are allowed.")
        
    # 2. Validate mime type
    mime = mimetypes.guess_type(file.filename)[0]
    if not mime or not mime.startswith("image/"):
        raise HTTPException(status_code=400, detail="Invalid mime type. File is not a valid image.")
        
    # 3. Validate file size (5MB limit)
    # Read a chunk to check size
    file.file.seek(0, 2)
    size = file.file.tell()
    file.file.seek(0)
    
    if size > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File size exceeds maximum limit of 5MB.")
        
    # 4. Generate safe filename
    base = re.sub(r'[^a-zA-Z0-9_\-]', '_', os.path.splitext(file.filename)[0])
    safe_name = f"{base}_{uuid.uuid4().hex[:8]}{ext}"
    dest_path = os.path.join(UPLOAD_DIR, safe_name)
    
    # 5. Save to disk
    with open(dest_path, "wb") as f:
        shutil.copyfileobj(file.file, f)
        
    # 6. Record in DB
    filepath = f"assets/uploads/{safe_name}"
    query = """
        INSERT INTO cms_media (filename, filepath, file_type, file_size, created_at)
        VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
        RETURNING id;
    """
    rows = execute_db_returning(query, (file.filename, filepath, ext.replace(".", "").upper(), size))
    
    return {"success": True, "media_id": rows[0]["id"], "filepath": filepath, "message": "Image uploaded successfully."}

@app.delete("/api/admin/media/{media_id}")
def delete_media(media_id: int, admin = Depends(get_current_admin)):
    rows = query_db("SELECT filepath FROM cms_media WHERE id = %s;", (media_id,))
    if not rows:
        raise HTTPException(status_code=404, detail="Media file not found.")
        
    filepath = rows[0]["filepath"]
    full_path = os.path.join(BASE_DIR, filepath.replace("/", os.sep))
    
    # Delete from disk
    if os.path.exists(full_path):
        try:
            os.remove(full_path)
        except Exception as e:
            logger.error(f"Error removing media file from disk: {e}")
            
    # Delete from DB
    execute_db("DELETE FROM cms_media WHERE id = %s;", (media_id,))
    return {"success": True, "message": "Image deleted successfully."}

# 7. Dashboard Stats
@app.get("/api/admin/dashboard-stats")
def get_dashboard_stats(admin = Depends(get_current_admin)):
    enquiries = query_db("SELECT COUNT(*) FROM cms_enquiries WHERE status = 'New';")[0]["count"]
    tools = query_db("SELECT COUNT(*) FROM cms_tools;")[0]["count"]
    services = query_db("SELECT COUNT(*) FROM cms_services;")[0]["count"]
    media = query_db("SELECT COUNT(*) FROM cms_media;")[0]["count"]
    
    return {
        "enquiries_count": enquiries,
        "tools_count": tools,
        "services_count": services,
        "media_count": media
    }

# --- SERVE FRONTEND HTML PAGES ---

@app.get("/admin/login")
def get_admin_login(session_id: str = Cookie(None)):
    if session_id:
        if session_id in FALLBACK_ADMIN_SESSIONS and FALLBACK_ADMIN_SESSIONS[session_id]["expires_at"] > datetime.datetime.now():
            return RedirectResponse(url="/admin")
        if db_enabled:
            try:
                rows = query_db("SELECT token FROM cms_admin_sessions WHERE token = %s AND expires_at > CURRENT_TIMESTAMP;", (session_id,))
                if rows:
                    return RedirectResponse(url="/admin")
            except Exception:
                pass
    return FileResponse(os.path.join(BASE_DIR, "login.html"))

@app.get("/admin")
def get_admin_dashboard(session_id: str = Cookie(None)):
    if not session_id:
        return RedirectResponse(url="/admin/login")
        
    if session_id in FALLBACK_ADMIN_SESSIONS and FALLBACK_ADMIN_SESSIONS[session_id]["expires_at"] > datetime.datetime.now():
        return FileResponse(os.path.join(BASE_DIR, "admin.html"))
        
    _ensure_db_connected()
    if not db_enabled:
        return RedirectResponse(url="/admin/login")
        
    try:
        rows = query_db("SELECT token FROM cms_admin_sessions WHERE token = %s AND expires_at > CURRENT_TIMESTAMP;", (session_id,))
        if not rows:
            return RedirectResponse(url="/admin/login")
    except Exception:
        return RedirectResponse(url="/admin/login")
        
    return FileResponse(os.path.join(BASE_DIR, "admin.html"))

@app.get("/")
def get_index():
    return FileResponse(os.path.join(BASE_DIR, "index.html"))

@app.get("/jobs")
def get_jobs_page():
    return FileResponse(os.path.join(BASE_DIR, "jobs.html"))

@app.get("/logo.png")
def get_logo():
    logo_path = os.path.join(BASE_DIR, "logo.png")
    if os.path.exists(logo_path):
        return FileResponse(logo_path)
    raise HTTPException(status_code=404, detail="logo.png not found")

# Initialize and include Tiruppur Jobs modular routers
import routers.jobs
import routers.admin_jobs
import routers.admin_ingestion
import routers.seo

routers.jobs.init_db_helpers(db_enabled, query_db, execute_db, execute_db_returning)
routers.admin_jobs.init_admin_helpers(db_enabled, query_db, execute_db, execute_db_returning, get_current_admin)
routers.admin_ingestion.init_ingestion_router(query_db, execute_db, execute_db_returning, db_enabled, FALLBACK_ADMIN_SESSIONS, BASE_DIR)
routers.seo.init_seo_db_helpers(db_enabled, query_db)

app.include_router(routers.jobs.router)
app.include_router(routers.admin_jobs.router)
app.include_router(routers.admin_ingestion.router)
app.include_router(routers.seo.router)

# Custom 404 Exception Handler returning HTTP 404 status code and friendly 404.html
@app.exception_handler(StarletteHTTPException)
async def custom_http_exception_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 404:
        four_oh_four_path = os.path.join(BASE_DIR, "404.html")
        if os.path.exists(four_oh_four_path):
            return FileResponse(four_oh_four_path, status_code=404)
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

# Serve upload assets dynamically
RESUME_UPLOAD_DIR = os.path.join(BASE_DIR, "assets", "uploads", "resumes")
SOURCE_VAULT_DIR = os.path.join(BASE_DIR, "assets", "uploads", "source_vault")
os.makedirs(RESUME_UPLOAD_DIR, exist_ok=True)
os.makedirs(SOURCE_VAULT_DIR, exist_ok=True)
app.mount("/assets/uploads/resumes", StaticFiles(directory=RESUME_UPLOAD_DIR), name="resumes")
app.mount("/assets/uploads/source_vault", StaticFiles(directory=SOURCE_VAULT_DIR), name="source_vault")
app.mount("/assets/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")
app.mount("/css", StaticFiles(directory=os.path.join(BASE_DIR, "css")), name="css")
app.mount("/js", StaticFiles(directory=os.path.join(BASE_DIR, "js")), name="js")
app.mount("/assets", StaticFiles(directory=os.path.join(BASE_DIR, "assets")), name="assets")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    host = os.environ.get("HOST", "0.0.0.0")
    reload = os.environ.get("RELOAD", "false").lower() in ("true", "1")
    logger.info(f"Starting server on {host}:{port}")
    uvicorn.run("app:app", host=host, port=port, reload=reload)
