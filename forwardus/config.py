"""Application configuration."""

from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # python-dotenv is optional
    load_dotenv = None

BASE_DIR = Path(__file__).resolve().parent

if load_dotenv:
    load_dotenv(BASE_DIR / ".env")


def _database_url() -> str:
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        return f"sqlite:///{BASE_DIR / 'instance' / 'forwardus.db'}"
    # Render provides postgres:// URLs; SQLAlchemy 2.x needs an explicit driver (psycopg 3).
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


class Config:
    """Base configuration loaded from environment variables."""

    DEBUG = os.getenv("FLASK_DEBUG", "0") == "1"
    PORT = int(os.getenv("PORT", "5000"))
    SECRET_KEY = os.getenv("SECRET_KEY") or "forwardus-local-dev-key"

    SQLALCHEMY_DATABASE_URI = _database_url()
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    DATA_DIR = BASE_DIR / "data"
    MOCK_DATA_DIR = DATA_DIR / "mock"

    EXCHANGE_RATE_USD_KRW = float(os.getenv("EXCHANGE_RATE_USD_KRW", "1380"))
    API_TIMEOUT_SECONDS = float(os.getenv("API_TIMEOUT_SECONDS", "8"))

    SCHEDULE_API_KEY = os.getenv("SCHEDULE_API_KEY", "")
    TRACKING_API_KEY = os.getenv("TRACKING_API_KEY", "")
    CUSTOMS_API_KEY = os.getenv("CUSTOMS_API_KEY", "")
    EXCHANGE_API_KEY = os.getenv("EXCHANGE_API_KEY", "")
    AI_API_KEY = os.getenv("AI_API_KEY", "")


class TestConfig(Config):
    """Configuration for automated tests (in-memory database)."""

    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
