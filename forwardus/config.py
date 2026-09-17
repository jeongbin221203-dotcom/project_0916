"""Application configuration."""

from __future__ import annotations

import os


class Config:
    """Base configuration loaded from environment variables."""

    DEBUG = os.getenv("FLASK_DEBUG", "0") == "1"
    PORT = int(os.getenv("PORT", "5000"))
    SECRET_KEY = os.getenv("SECRET_KEY", "forwardus-prototype-local")
    EXCHANGE_RATE_USD_KRW = float(os.getenv("EXCHANGE_RATE_USD_KRW", "1380"))
    DATA_SOURCE = os.getenv("DATA_SOURCE", "mock")

