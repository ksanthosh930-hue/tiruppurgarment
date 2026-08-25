import os
import sys
import psycopg2
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash

# Load environment variables
load_dotenv(dotenv_path="d:\\WEBSITE\\.env")

ADMIN_INITIAL_PASSWORD = os.getenv("ADMIN_INITIAL_PASSWORD")
DATABASE_URL = os.getenv("DATABASE_URL")

print("Checking ADMIN_INITIAL_PASSWORD environment variable...")
if not ADMIN_INITIAL_PASSWORD or not ADMIN_INITIAL_PASSWORD.strip():
    print("\n[ERROR] CRITICAL CONFIGURATION FAILURE:")
    print("------------------------------------------------------------------------")
    print("ADMIN_INITIAL_PASSWORD environment variable is missing or empty in .env.")
    print("Migration has been aborted to prevent creation of insecure default passwords.")
    print("Please set ADMIN_INITIAL_PASSWORD in d:\\WEBSITE\\.env and retry.")
    print("------------------------------------------------------------------------\n")
    sys.exit(1)

print("ADMIN_INITIAL_PASSWORD is set. Proceeding with migration...")

if not DATABASE_URL:
    print("[ERROR] DATABASE_URL environment variable is missing.")
    sys.exit(1)

try:
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()
    
    # 1. Create cms_settings table
    print("Creating cms_settings table...")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cms_settings (
            key VARCHAR(255) PRIMARY KEY,
            value TEXT NOT NULL
        );
    """)
    
    # 2. Create cms_sections table
    print("Creating cms_sections table...")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cms_sections (
            section_name VARCHAR(255) PRIMARY KEY,
            content JSONB NOT NULL
        );
    """)
    
    # 3. Create cms_tools table
    print("Creating cms_tools table...")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cms_tools (
            id SERIAL PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            description TEXT NOT NULL,
            icon VARCHAR(255) NOT NULL,
            url VARCHAR(255) NOT NULL,
            status VARCHAR(50) NOT NULL DEFAULT 'ACTIVE',
            display_order INTEGER DEFAULT 0,
            featured BOOLEAN DEFAULT FALSE
        );
    """)
    
    # 4. Create cms_services table
    print("Creating cms_services table...")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cms_services (
            id SERIAL PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            short_description TEXT NOT NULL,
            detailed_description TEXT,
            icon VARCHAR(255) NOT NULL,
            image_url VARCHAR(255),
            status VARCHAR(50) NOT NULL DEFAULT 'ACTIVE',
            display_order INTEGER DEFAULT 0
        );
    """)
    
    # 5. Create cms_categories table
    print("Creating cms_categories table...")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cms_categories (
            id SERIAL PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            slug VARCHAR(255) NOT NULL UNIQUE,
            description TEXT
        );
    """)
    
    # 6. Create cms_articles table
    print("Creating cms_articles table...")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cms_articles (
            id SERIAL PRIMARY KEY,
            title VARCHAR(255) NOT NULL,
            slug VARCHAR(255) NOT NULL UNIQUE,
            category_id INTEGER REFERENCES cms_categories(id) ON DELETE SET NULL,
            short_description TEXT NOT NULL,
            full_content TEXT NOT NULL,
            featured_image VARCHAR(255),
            author VARCHAR(255) NOT NULL,
            publish_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status VARCHAR(50) NOT NULL DEFAULT 'DRAFT',
            featured BOOLEAN DEFAULT FALSE,
            seo_title VARCHAR(255),
            seo_description TEXT,
            keywords VARCHAR(255)
        );
    """)
    
    # 7. Create cms_enquiries table
    print("Creating cms_enquiries table...")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cms_enquiries (
            id SERIAL PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            company VARCHAR(255),
            email VARCHAR(255) NOT NULL,
            phone VARCHAR(50),
            message TEXT NOT NULL,
            created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status VARCHAR(50) NOT NULL DEFAULT 'New'
        );
    """)
    
    # 8. Create cms_media table
    print("Creating cms_media table...")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cms_media (
            id SERIAL PRIMARY KEY,
            filename VARCHAR(255) NOT NULL,
            filepath VARCHAR(255) NOT NULL,
            file_type VARCHAR(50),
            file_size INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    
    # 9. Create cms_admin_sessions table
    print("Creating cms_admin_sessions table...")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cms_admin_sessions (
            token VARCHAR(255) PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            expires_at TIMESTAMP NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    
    # 10. Update/Create admin user with Werkzeug hash
    print("Creating or updating admin account...")
    hashed_pwd = generate_password_hash(ADMIN_INITIAL_PASSWORD, method="scrypt")
    
    # Check if admin user exists in users table
    cursor.execute("SELECT id FROM users WHERE username = 'admin';")
    user_row = cursor.fetchone()
    
    if user_row:
        user_id = user_row[0]
        print(f"Admin user exists (id={user_id}). Updating password...")
        cursor.execute("""
            UPDATE users 
            SET password_hash = %s, updated_at = CURRENT_TIMESTAMP 
            WHERE id = %s;
        """, (hashed_pwd, user_id))
    else:
        print("Admin user does not exist. Creating admin user...")
        cursor.execute("""
            INSERT INTO users (username, email, password_hash, is_active, created_at, updated_at)
            VALUES ('admin', 'admin@tirupurgarments.com', %s, TRUE, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            RETURNING id;
        """, (hashed_pwd,))
        user_id = cursor.fetchone()[0]
        
    # Check if user is in admins table
    cursor.execute("SELECT id FROM admins WHERE user_id = %s;", (user_id,))
    admin_row = cursor.fetchone()
    if not admin_row:
        print("Adding admin user reference to admins table...")
        cursor.execute("""
            INSERT INTO admins (user_id, role, created_at, updated_at)
            VALUES (%s, 'superadmin', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);
        """, (user_id,))
        
    # 11. Seed initial tools if tools table is empty
    cursor.execute("SELECT COUNT(*) FROM cms_tools;")
    tools_count = cursor.fetchone()[0]
    if tools_count == 0:
        print("Seeding initial tools...")
        cursor.execute("""
            INSERT INTO cms_tools (name, description, icon, url, status, display_order, featured)
            VALUES 
            ('Technical SAM / SMV Calculator', 'Professional garment operation-based SAM / SMV calculation tool with machine, operation, specification, speed, SPI, allowance and calculation support.', '⚒', '/tools/sam-calculator', 'ACTIVE', 1, TRUE),
            ('Line Planning Tool', 'Digital line planning and production balancing solution for garment manufacturing.', '▥', '#', 'COMING_SOON', 2, FALSE);
        """)
        
    # 12. Seed initial services if services table is empty
    cursor.execute("SELECT COUNT(*) FROM cms_services;")
    services_count = cursor.fetchone()[0]
    if services_count == 0:
        print("Seeding initial services...")
        cursor.execute("""
            INSERT INTO cms_services (name, short_description, icon, status, display_order)
            VALUES 
            ('Report Automation', 'Automate repetitive daily, weekly and monthly garment reports, reducing manual Excel work and improving reporting accuracy.', '⌁', 'ACTIVE', 1),
            ('Excel Automation', 'Convert repetitive Excel-based processes into automated workflows using formulas, Power Query, Python and custom automation solutions.', '▤', 'ACTIVE', 2),
            ('Automated Salary Slip Distribution', 'Generate salary slips automatically and distribute them securely to employees through email.', '✉', 'ACTIVE', 3),
            ('Data Entry Automation', 'Automate repetitive data entry, file processing, data consolidation and system-to-system data transfer tasks.', '✎', 'ACTIVE', 4),
            ('Garment Process Automation', 'Digitize and automate repetitive garment business processes to reduce manual effort and improve operational efficiency.', '⚙', 'ACTIVE', 5),
            ('Custom Garment Automation', 'Build customized automation solutions based on your company''s existing Excel files, reports, workflows and business requirements.', '⌘', 'ACTIVE', 6);
        """)
        
    # 13. Seed default settings
    cursor.execute("SELECT COUNT(*) FROM cms_settings;")
    settings_count = cursor.fetchone()[0]
    if settings_count == 0:
        print("Seeding website settings...")
        cursor.execute("""
            INSERT INTO cms_settings (key, value)
            VALUES 
            ('site_name', 'DigiGarment'),
            ('tagline', 'Automate Your Garment Business'),
            ('logo_url', 'assets/images/logo-light.png'),
            ('favicon_url', 'assets/images/logo-light.png'),
            ('contact_email', 'info@digigarment.com'),
            ('contact_phone', '+91 XXXXXXXXXX'),
            ('address', 'Tirupur, Tamil Nadu, India'),
            ('whatsapp_number', ''),
            ('social_facebook', '#'),
            ('social_linkedin', '#'),
            ('social_youtube', '#'),
            ('social_instagram', '#'),
            ('footer_text', '© 2026 DigiGarment. All Rights Reserved.'),
            ('sam_calculator_url', 'http://127.0.0.1:5000/'),
            ('seo_meta_title', 'DigiGarment | Garment Automation & Digital Solutions'),
            ('seo_meta_description', 'DigiGarment - Garment automation and digital solutions for smarter garment businesses.'),
            ('seo_default_keywords', 'garment, automation, SAM, SMV, calculator'),
            ('seo_og_title', 'DigiGarment | Garment Automation & Digital Solutions'),
            ('seo_og_description', 'DigiGarment - Garment automation and digital solutions for smarter garment businesses.'),
            ('seo_og_image', ''),
            ('seo_google_analytics_id', ''),
            ('seo_search_indexing', 'true');
        """)
        
    # 14. Seed default sections (Hero / About)
    cursor.execute("SELECT COUNT(*) FROM cms_sections;")
    sections_count = cursor.fetchone()[0]
    if sections_count == 0:
        print("Seeding homepage sections content...")
        import json
        hero_content = {
            "eyebrow": "GARMENT TECHNOLOGY • AUTOMATION",
            "heading": "Empowering Garment Industries with Digital Solutions",
            "description": "Practical automation and digital solutions for garment businesses — from SAM/SMV calculation and Excel automation to reporting and repetitive process automation.",
            "primary_btn_text": "Explore SAM Calculator",
            "primary_btn_url": "#tools",
            "secondary_btn_text": "Talk to Us",
            "secondary_btn_url": "#contact",
            "image_url": "assets/images/hero-automation.jpg",
            "highlights": [
                "Garment Industry Focus",
                "SAM / SMV Technology",
                "Excel & Reporting Automation",
                "Business Process Automation"
            ]
        }
        about_content = {
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
            "image_url": "assets/images/hero-automation.jpg",
            "cta_text": "Learn More"
        }
        cursor.execute("""
            INSERT INTO cms_sections (section_name, content)
            VALUES 
            ('hero', %s),
            ('about', %s);
        """, (json.dumps(hero_content), json.dumps(about_content)))

    conn.commit()
    print("\nDatabase migration completed successfully!")
    
    cursor.close()
    conn.close()
except Exception as e:
    print(f"\n[ERROR] Database migration failed: {e}")
    sys.exit(1)
