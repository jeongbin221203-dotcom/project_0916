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


def json_body() -> dict:
    """보내 온 JSON 본문을 **반드시 dict 로** 돌려줍니다.

    왜 필요한가
      여태 `request.get_json(silent=True) or {}` 라고 적었습니다. 본문이
      `12345` 나 `"글자"` 나 `[]` 로 오면 `or {}` 가 듣지 않아(숫자·글자는
      참입니다) 그대로 서비스로 넘어갔고, 거기서 `payload.get(...)` 이
      `AttributeError` 로 터졌습니다. 이용자에게는 **500** 이 갑니다.
      무엇이 잘못됐는지 한마디도 없이 화면이 멈춥니다.

      흔들어 보니 /planning/api/schedules 와 /planning/api/departure-check 에서
      실제로 났습니다. 같은 자리가 21곳이라 한 곳에서 막습니다. (2026-09-26)
    """

    from flask import request

    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


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
