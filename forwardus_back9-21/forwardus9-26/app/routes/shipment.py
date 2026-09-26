"""Shipment list and detail screens."""

from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for

from app.models.shipment import SHIPMENT_STATUSES
from app.routes import load_shipment
from app.routes.auth import login_required
from app.services import ServiceError, shipment_service

shipment_bp = Blueprint("shipment", __name__, url_prefix="/shipments")


@shipment_bp.get("")
@login_required
def index():
    """예전 Shipments 목록. 목록은 Dashboard로 합쳤습니다. 옛 주소·즐겨찾기는 그리로 보냅니다."""

    status = request.args.get("status") or None
    if status not in SHIPMENT_STATUSES:
        status = None
    return redirect(url_for("dashboard.index", status=status))


@shipment_bp.get("/<shipment_id>")
def detail(shipment_id: str):
    shipment = load_shipment(shipment_id)
    return render_template("shipment/detail.html", **shipment_service.build_summary(shipment))


@shipment_bp.post("/<shipment_id>/status")
def change_status(shipment_id: str):
    shipment = load_shipment(shipment_id)
    try:
        shipment_service.transition(shipment, request.form.get("action", ""))
        flash(f"상태가 '{shipment.status_label}'(으)로 변경되었습니다.", "success")
    except ServiceError as exc:
        flash(str(exc), "error")
    return redirect(url_for("shipment.detail", shipment_id=shipment_id))
