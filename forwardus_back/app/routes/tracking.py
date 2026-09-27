"""Shipment tracking screen."""

from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for

from app.models.tracking_event import EVENT_LABELS, TRACKING_EVENTS
from app.routes import load_shipment
from app.services import ServiceError, tracking_service
from app.validators import ValidationError

tracking_bp = Blueprint("tracking", __name__, url_prefix="/tracking")


@tracking_bp.get("/<shipment_id>")
def detail(shipment_id: str):
    shipment = load_shipment(shipment_id)
    return render_template(
        "tracking/detail.html",
        shipment=shipment,
        event_options=[(code, EVENT_LABELS[code]) for code in TRACKING_EVENTS],
        **tracking_service.build_timeline(shipment),
    )


def _redirect(shipment_id: str):
    return redirect(url_for("tracking.detail", shipment_id=shipment_id))


@tracking_bp.post("/<shipment_id>/refresh")
def refresh(shipment_id: str):
    shipment = load_shipment(shipment_id)
    try:
        result = tracking_service.advance_mock(shipment)
        message = "Mock Tracking 이벤트를 추가했습니다."
        if result["eta_change"]:
            message += f" ETA가 {result['eta_change']['delay_days']:+d}일 변경되었습니다."
        flash(message, "error" if result["eta_change"] and result["eta_change"]["delay_days"] > 0 else "success")
    except ServiceError as exc:
        flash(str(exc), "error")
    return _redirect(shipment_id)


@tracking_bp.post("/<shipment_id>/events")
def add_event(shipment_id: str):
    shipment = load_shipment(shipment_id)
    try:
        tracking_service.add_manual_event(shipment, request.form.to_dict())
        flash("수동 이벤트를 기록했습니다.", "success")
    except (ValidationError, ServiceError) as exc:
        flash(str(exc), "error")
    return _redirect(shipment_id)


@tracking_bp.post("/<shipment_id>/eta")
def update_eta(shipment_id: str):
    shipment = load_shipment(shipment_id)
    try:
        change = tracking_service.update_eta_manually(shipment, request.form.to_dict())
        flash(f"ETA 변경을 기록했습니다. ({change['delay_days']:+d}일)" if change else "ETA가 기존과 같습니다.", "success")
    except (ValidationError, ServiceError) as exc:
        flash(str(exc), "error")
    return _redirect(shipment_id)
