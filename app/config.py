import os
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env")


def _get_env_cleaned(*keys, default=None):
    for key in keys:
        val = os.getenv(key)
        if val is not None:
            val = str(val).strip().strip("'\"")
            if val:
                return val
    return default


class Config:
    SECRET_KEY = _get_env_cleaned("SECRET_KEY", default="development-only-secret")
    DEBUG = os.getenv("FLASK_ENV", "development") == "development"
    DATABASE_URL = _get_env_cleaned(
        "DATABASE_URL",
        "POSTGRES_URL",
        "SUPABASE_DATABASE_URL",
        "SUPABASE_DB_URL",
        "POSTGRES_PRISMA_URL",
        "POSTGRES_URL_NON_POOLING",
        "DATABASE_URI",
    )
    SUPABASE_URL = _get_env_cleaned("SUPABASE_URL", "NEXT_PUBLIC_SUPABASE_URL", "SUPABASE_PROJECT_URL")
    SUPABASE_SERVICE_ROLE_KEY = _get_env_cleaned("SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_SERVICE_KEY", "SUPABASE_KEY")
    SUPABASE_STORAGE_BUCKET = _get_env_cleaned("SUPABASE_STORAGE_BUCKET", default="profile-images")
    GOOGLE_CLIENT_ID = _get_env_cleaned("GOOGLE_CLIENT_ID")
    GOOGLE_CLIENT_SECRET = _get_env_cleaned("GOOGLE_CLIENT_SECRET")
    GEMINI_API_KEY = _get_env_cleaned("GEMINI_API_KEY", "GOOGLE_API_KEY")
    GEMINI_MODEL = _get_env_cleaned("GEMINI_MODEL", default="gemini-3.7-flash")
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    _SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE")
    SESSION_COOKIE_SECURE = (
        _SESSION_COOKIE_SECURE.lower() == "true"
        if _SESSION_COOKIE_SECURE is not None
        else os.getenv("FLASK_ENV", "development") != "development"
    )
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)
