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
        request.args.get("origin"),
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


@planning_bp.get("/api/exchange-rate")
def api_exchange_rate():
    """통화별 원화 환율. 운임을 원화로 환산해 보여주는 데 씁니다."""

    return jsonify(planning_service.exchange_rates())


@planning_bp.get("/api/tariff-summary")
def api_tariff_summary():
    """HS 후보별로 도착국에 쓸 수 있는 협정을 한 줄로 요약합니다."""

    codes = [code.strip() for code in request.args.get("hs", "").split(",")]
    return jsonify({"success": True, "data": planning_service.tariff_summaries(
        codes, request.args.get("country", ""))})


@planning_bp.get("/api/tariff")
def api_tariff():
    """고른 품목과 도착국에 적용되는 협정·세율."""

    return jsonify({"success": True, "data": planning_service.tariff_guide(
        request.args.get("hs", ""), request.args.get("country", ""))})


@planning_bp.get("/api/destination-tariff")
def api_destination_tariff():
    """도착국이 실제로 매기는 관세와 그 나라의 세분 부호."""

    return jsonify({"success": True, "data": planning_service.destination_tariff(
        request.args.get("hs", ""), request.args.get("country", ""))})


@planning_bp.get("/api/un-numbers")
def api_un_numbers():
    """UN번호 찾기. 물품 이름이나 번호로 검색합니다."""

    return jsonify({"success": True,
                    "data": planning_service.un_number_search(request.args.get("q", ""))})


@planning_bp.get("/api/dangerous-goods")
def api_dangerous_goods():
    """고른 위험물 등급을 어떻게 보내야 하는지 안내합니다."""

    return jsonify({"success": True, "data": planning_service.dangerous_goods_guide(
        request.args.get("dg_class", ""), request.args.get("mode", "SEA"),
        request.args.get("country", ""))})


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

    return jsonify({"success": True, "data": planning_service.transit_summary(request.args.get("origin", ""), request.args.get("destination", ""))})


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
