"""Operations dashboard."""

from __future__ import annotations

from flask import Blueprint, render_template

from app.services import analytics_service

dashboard_bp = Blueprint("dashboard", __name__, url_prefix="/dashboard")


@dashboard_bp.get("")
def index():
    return render_template("dashboard/index.html", **analytics_service.build_dashboard())
