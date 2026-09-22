"""Shared Flask extension instances."""

from __future__ import annotations

from datetime import datetime, timezone

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


def utc_now() -> datetime:
    """Naive UTC timestamp (datetime.utcnow() is deprecated since Python 3.12)."""

    return datetime.now(timezone.utc).replace(tzinfo=None)
