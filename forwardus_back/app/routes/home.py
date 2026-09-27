"""Home screen."""

from __future__ import annotations

from flask import Blueprint, render_template

from app.services import shipment_service

home_bp = Blueprint("home", __name__)


@home_bp.get("/")
def index():
    recent = shipment_service.list_shipments()[:3]
    return render_template("home/index.html", recent=recent)
