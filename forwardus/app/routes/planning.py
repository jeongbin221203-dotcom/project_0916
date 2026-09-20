"""Shipment planning screens and JSON endpoints."""

from __future__ import annotations

from flask import Blueprint, jsonify, render_template, request, url_for

from app.routes import error_response
from app.services import ServiceError, planning_service
from app.validators import ValidationError

planning_bp = Blueprint("planning", __name__, url_prefix="/planning")


@planning_bp.get("")
def index():
    return render_template("planning/index.html")


@planning_bp.get("/new")
def new():
    return render_template("planning/new.html", options=planning_service.get_form_options())


@planning_bp.get("/api/locations")
def api_locations():
    result = planning_service.search_locations(
        request.args.get("q", ""),
        request.args.get("mode", "SEA"),
        request.args.get("role"),
        request.args.get("country"),
    )
    return jsonify(result), (200 if result["success"] else 502)


@planning_bp.get("/api/countries")
def api_countries():
    result = planning_service.list_countries(request.args.get("mode", "SEA"), request.args.get("role"))
    return jsonify(result), (200 if result["success"] else 502)


@planning_bp.get("/api/unlocode")
def api_unlocode():
    """직접 입력 칸에서 실제 UN/LOCODE 후보를 찾습니다."""

    result = planning_service.search_unlocode(
        request.args.get("q", ""),
        request.args.get("role"),
        request.args.get("country"),
        request.args.get("mode", "SEA"),
    )
    return jsonify(result), (200 if result["success"] else 502)


@planning_bp.get("/api/hs-codes")
def api_hs_codes():
    result = planning_service.search_hs_codes(request.args.get("q", ""))
    return jsonify(result), (200 if result["success"] else 502)


@planning_bp.post("/api/cargo")
def api_cargo():
    try:
        return jsonify({"success": True, "data": planning_service.calculate_cargo(request.get_json(silent=True) or {})})
    except (ValidationError, ServiceError) as exc:
        return error_response(exc)


@planning_bp.post("/api/schedules")
def api_schedules():
    try:
        return jsonify({"success": True, "data": planning_service.search_schedules(request.get_json(silent=True) or {})})
    except (ValidationError, ServiceError) as exc:
        return error_response(exc)


@planning_bp.get("/api/transit-estimate")
def api_transit_estimate():
    """선택한 도착지 구간의 해상·항공 예상 소요일."""

    return jsonify({"success": True, "data": planning_service.transit_summary(request.args.get("destination", ""))})


@planning_bp.post("/api/schedule-outlook")
def api_schedule_outlook():
    """해상·항공 소요시간과 납기 여유."""

    try:
        return jsonify({"success": True,
                        "data": planning_service.schedule_outlook(request.get_json(silent=True) or {})})
    except (ValidationError, ServiceError) as exc:
        return error_response(exc)


@planning_bp.post("/api/departure-check")
def api_departure_check():
    """출발 희망일 여유(Seller 예정일) 확인."""

    try:
        return jsonify({"success": True, "data": planning_service.check_departure_date(request.get_json(silent=True) or {})})
    except (ValidationError, ServiceError) as exc:
        return error_response(exc)


@planning_bp.post("/api/reverse-schedule")
def api_reverse_schedule():
    try:
        return jsonify({"success": True, "data": planning_service.reverse_schedule(request.get_json(silent=True) or {})})
    except (ValidationError, ServiceError) as exc:
        return error_response(exc)


@planning_bp.post("/api/shipments")
def api_create_shipment():
    try:
        shipment = planning_service.create_shipment(request.get_json(silent=True) or {})
    except (ValidationError, ServiceError) as exc:
        return error_response(exc)
    return jsonify({
        "success": True,
        "data": {
            "shipment_id": shipment.shipment_id,
            "url": url_for("shipment.detail", shipment_id=shipment.shipment_id),
        },
    }), 201
