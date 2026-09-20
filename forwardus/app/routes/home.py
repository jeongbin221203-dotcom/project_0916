"""Home screen."""

from __future__ import annotations

from flask import Blueprint, jsonify, render_template, request

from app.services import ServiceError, shipment_service, support_chat_service

home_bp = Blueprint("home", __name__)


@home_bp.get("/")
def index():
    recent = shipment_service.list_shipments()[:3]
    return render_template("home/index.html", recent=recent)


@home_bp.post("/api/support-chat")
def api_support_chat():
    """어느 화면에서나 열 수 있는 고객상담 창구."""

    payload = request.get_json(silent=True) or {}
    try:
        result = support_chat_service.ask(payload.get("question", ""),
                                          payload.get("history") or [])
    except ServiceError as error:
        return jsonify({"success": False, "message": str(error),
                        "error_code": error.error_code, "source": "api"}), error.status
    return jsonify(result), (200 if result["success"] else 502)
