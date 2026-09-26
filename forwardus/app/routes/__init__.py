"""Blueprint registration and shared route helpers."""

from __future__ import annotations

from flask import Flask, abort, jsonify, make_response

from app.services import ServiceError
from app.validators import ValidationError


def error_response(exc: Exception):
    """Convert a service or validation error into a normalized JSON response."""

    if isinstance(exc, ValidationError):
        return jsonify({"success": False,
                        "error_code": getattr(exc, "code", "") or "VALIDATION_ERROR",
                        "message": str(exc), "field": exc.field}), 400
    if isinstance(exc, ServiceError):
        return jsonify({"success": False, "error_code": exc.error_code, "message": str(exc)}), exc.status
    raise exc


def load_shipment(shipment_id: str):
    """주소의 Shipment를 읽습니다. 볼 권한이 없으면 없는 것처럼 404로 답합니다."""

    from app.routes.auth import current_user, login_required_response
    from app.services import shipment_service

    denied = login_required_response()
    if denied is not None:
        abort(make_response(denied))
    try:
        return shipment_service.get_or_404(shipment_id, viewer=current_user())
    except ServiceError:
        abort(404)


def register_blueprints(flask_app: Flask) -> None:
    from app.routes.assistant import assistant_bp
    from app.routes.auth import auth_bp
    from app.routes.contract import contract_bp
    from app.routes.dashboard import dashboard_api_bp, dashboard_bp
    from app.routes.document import document_bp
    from app.routes.lookup import lookup_bp
    from app.routes.home import home_bp
    from app.routes.planning import planning_bp
    from app.routes.shipment import shipment_bp
    from app.routes.tracking import tracking_bp
    from app.routes.work_draft import work_draft_bp

    for blueprint in (home_bp, planning_bp, shipment_bp, document_bp, tracking_bp,
                      assistant_bp, dashboard_bp, dashboard_api_bp, lookup_bp, auth_bp,
                      work_draft_bp, contract_bp):
        flask_app.register_blueprint(blueprint)
