"""Application configuration. All secrets come from environment variables."""
import logging
import os
import secrets
from datetime import timedelta

from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger(__name__)


def _env(name, default=""):
    """Read an env var; blank values and untouched '.env.example' placeholders count as unset."""
    value = (os.getenv(name) or "").strip()
    if not value or value.lower().startswith("replace_with"):
        return default
    return value


def _bool(value, default=False):
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _int(name, default):
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def normalize_database_url(url: str) -> str:
    """Make a Supabase/Heroku-style URL usable by SQLAlchemy + psycopg2."""
    if not url:
        return url
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg2://" + url[len("postgresql://"):]
    if url.startswith("postgresql+psycopg2://") and "sslmode=" not in url:
        host_part = url.split("@")[-1]
        if not host_part.startswith(("localhost", "127.0.0.1")):
            url += ("&" if "?" in url else "?") + "sslmode=require"
    return url


class Config:
    ENV = _env("FLASK_ENV", "production").lower()
    IS_PRODUCTION = ENV == "production"
    TESTING = False

    SECRET_KEY = _env("SECRET_KEY") or None
    DATABASE_URL = normalize_database_url(_env("DATABASE_URL"))
    DB_POOL_SIZE = _int("DB_POOL_SIZE", 5)
    DB_MAX_OVERFLOW = _int("DB_MAX_OVERFLOW", 5)
    AUTO_INIT_DB = _bool(os.getenv("AUTO_INIT_DB"), True)
    SEED_ON_STARTUP = _bool(os.getenv("SEED_ON_STARTUP"), True)

    APP_TIMEZONE = os.getenv("APP_TIMEZONE", "Asia/Kolkata")

    # Sessions / cookies
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = IS_PRODUCTION
    PERMANENT_SESSION_LIFETIME = timedelta(days=30)
    WTF_CSRF_TIME_LIMIT = None
    MAX_CONTENT_LENGTH = 64 * 1024

    # Rate limits
    RATELIMIT_ENABLED = _bool(os.getenv("RATELIMIT_ENABLED"), True)
    RATELIMIT_STORAGE_URI = os.getenv("RATELIMIT_STORAGE_URI", "memory://")
    LOGIN_RATE_LIMIT = os.getenv("LOGIN_RATE_LIMIT", "10 per minute")
    REGISTER_RATE_LIMIT = os.getenv("REGISTER_RATE_LIMIT", "5 per minute")
    FEEDBACK_RATE_LIMIT = os.getenv("FEEDBACK_RATE_LIMIT", "5 per minute")

    # Quiz rules
    QUESTIONS_PER_GAME = _int("QUESTIONS_PER_GAME", 10)
    ALL_QUIZ_QUESTIONS = _int("ALL_QUIZ_QUESTIONS", 56)
    DAILY_QUESTION_COUNT = min(_int("DAILY_QUESTION_COUNT", 50), 50)
    HINTS_PER_GAME = _int("HINTS_PER_GAME", 10)
    DAILY_HINTS = _int("DAILY_HINTS", 5)
    PAGE_SIZE = 20

    # Gemini (backend only)
    GEMINI_API_KEY = _env("GEMINI_API_KEY")
    GEMINI_MODEL = _env("GEMINI_MODEL", "gemini-3.1-flash-lite")
    GEMINI_TIMEOUT = _int("GEMINI_TIMEOUT", 30)
    GEMINI_RETRIES = _int("GEMINI_RETRIES", 2)
    GEMINI_MAX_CALLS_PER_MINUTE = _int("GEMINI_MAX_CALLS_PER_MINUTE", 8)
    GEMINI_BATCH_SIZE = _int("GEMINI_BATCH_SIZE", 10)
    MAX_GENERATIONS_PER_REQUEST = _int("MAX_GENERATIONS_PER_REQUEST", 3)

    ADMIN_API_TOKEN = _env("ADMIN_API_TOKEN")


def finalize(app):
    """Validate/complete configuration after loading. Fails fast on unsafe production setups."""
    cfg = app.config
    if not cfg.get("SECRET_KEY"):
        if cfg.get("IS_PRODUCTION") and not cfg.get("TESTING"):
            raise RuntimeError("SECRET_KEY environment variable is required in production.")
        cfg["SECRET_KEY"] = secrets.token_hex(32)
        log.warning("SECRET_KEY not set; using a temporary random key (sessions reset on restart).")
    if not cfg.get("DATABASE_URL"):
        if cfg.get("IS_PRODUCTION") and not cfg.get("TESTING"):
            raise RuntimeError("DATABASE_URL environment variable is required in production.")
        cfg["DATABASE_URL"] = "sqlite:///dev.sqlite3"
        log.warning("DATABASE_URL not set; using local SQLite for development ONLY.")
    elif cfg["DATABASE_URL"].startswith("sqlite") and cfg.get("IS_PRODUCTION") and not cfg.get("TESTING"):
        raise RuntimeError("SQLite is not allowed in production. Set DATABASE_URL to Supabase PostgreSQL.")
    try:
        from sqlalchemy.engine import make_url
        make_url(cfg["DATABASE_URL"])
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("DATABASE_URL is not a valid database URL. Expected something like "
                           "postgresql://USER:PASSWORD@HOST:5432/postgres (URL-encode special "
                           "characters in the password).") from exc
    if not cfg.get("GEMINI_API_KEY"):
        log.warning("GEMINI_API_KEY is not set: AI generation disabled, stored questions only.")
