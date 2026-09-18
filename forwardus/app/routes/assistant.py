"""AI Export Assistant screen."""

from __future__ import annotations

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for

from app.routes import error_response, load_shipment
from app.services import ServiceError, assistant_service
from app.validators import ValidationError

assistant_bp = Blueprint("assistant", __name__, url_prefix="/assistant")


@assistant_bp.get("/<shipment_id>")
def index(shipment_id: str):
    shipment = load_shipment(shipment_id)
    return render_template(
        "assistant/index.html",
        shipment=shipment,
        readiness=assistant_service.export_readiness(shipment),
        cost=assistant_service.cost_explanation(shipment),
        exception=assistant_service.exception_guide(shipment),
        cashflow=assistant_service.cash_flow(shipment),
    )


@assistant_bp.post("/<shipment_id>/api/ask")
def api_ask(shipment_id: str):
    shipment = load_shipment(shipment_id)
    payload = request.get_json(silent=True) or {}
    try:
        return jsonify({"success": True, "data": assistant_service.answer_question(shipment, payload.get("question", ""))})
    except (ValidationError, ServiceError) as exc:
        return error_response(exc)


def _redirect(shipment_id: str):
    return redirect(url_for("assistant.index", shipment_id=shipment_id) + "#cashflow")


@assistant_bp.post("/<shipment_id>/payments")
def add_payment(shipment_id: str):
    shipment = load_shipment(shipment_id)
    try:
        if request.form.get("preset") == "logistics":
            assistant_service.add_logistics_payment(shipment)
        else:
            assistant_service.add_payment(shipment, request.form.to_dict())
        flash("결제 일정을 추가했습니다.", "success")
    except (ValidationError, ServiceError) as exc:
        flash(str(exc), "error")
    return _redirect(shipment_id)


@assistant_bp.post("/<shipment_id>/payments/<int:payment_id>/delete")
def delete_payment(shipment_id: str, payment_id: int):
    shipment = load_shipment(shipment_id)
    try:
        assistant_service.remove_payment(shipment, payment_id)
        flash("결제 일정을 삭제했습니다.", "success")
    except ServiceError as exc:
        flash(str(exc), "error")
    return _redirect(shipment_id)
