import os
from datetime import timedelta
from dotenv import load_dotenv

# Load environment variables from .env file (force override to prioritize local .env values)
load_dotenv(override=True)

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY')
    if not SECRET_KEY:
        # Generate a fallback secret key for development, but warn in logs
        SECRET_KEY = 'tirupur-garments-default-dev-key-change-in-production'
        
    DATABASE_URL = os.environ.get('DATABASE_URL')
    
    if not DATABASE_URL:
        raise RuntimeError(
            "CRITICAL CONFIGURATION ERROR: The 'DATABASE_URL' environment variable is not set. "
            "Tirupur Garments requires a Supabase PostgreSQL database connection to start. "
            "Please create a '.env' file in the root directory and configure 'DATABASE_URL'."
        )
        
    # Support PostgreSQL urls starting with 'postgres://' which is common on Supabase/Heroku,
    # but SQLAlchemy 1.4+ expects 'postgresql://'
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
        
    SQLALCHEMY_DATABASE_URI = DATABASE_URL
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Session Cookie Security Configuration
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    SESSION_COOKIE_SECURE = os.environ.get('FLASK_ENV') == 'production'
    PERMANENT_SESSION_LIFETIME = timedelta(hours=2)
