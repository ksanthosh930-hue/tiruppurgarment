import os
from datetime import timedelta
from dotenv import load_dotenv

# Load environment variables from .env file (force override to prioritize local .env values)
load_dotenv(override=True)

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY')
    if not SECRET_KEY:
        raise RuntimeError(
            "CRITICAL CONFIGURATION ERROR: The 'SECRET_KEY' environment variable is not set. "
            "Set a secure secret key in the environment before starting the app."
        )

    DATABASE_URL = os.environ.get('DATABASE_URL')

    if not DATABASE_URL:
        raise RuntimeError(
            "CRITICAL CONFIGURATION ERROR: The 'DATABASE_URL' environment variable is not set. "
            "Tirupur Garments requires a Supabase PostgreSQL database connection to start. "
            "Please configure 'DATABASE_URL' in the environment or .env file."
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
