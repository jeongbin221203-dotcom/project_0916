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


def collector_response(result: dict):
    """기관 조회 결과를 응답으로. **실패 사유에 맞는 상태코드를 줍니다.**

    왜 필요한가
      여태 `200 if result["success"] else 502` 라고 적었습니다. 그래서 **적은
      번호가 잘못된 것**(우리 잘못)도 502(기관 장애)로 나갔습니다. 화면과
      감시 도구는 그걸 "관세청이 죽었다"로 읽습니다. 관세청은 멀쩡한데
      우리가 잘못 적은 것입니다. 고쳐야 할 곳을 엉뚱한 데서 찾게 됩니다.
      전 화면을 그려 보다 /customs-filing/clearance-code 에서 찾았고,
      같은 자리가 7곳이라 한 곳에서 막습니다. (2026-09-26)

        VALIDATION_ERROR   400  우리가 잘못 적었습니다
        API_AUTH_FAILED    503  우리 쪽 키가 없거나 막혔습니다 (기관은 멀쩡)
        그 밖                502  기관이 응답하지 않습니다
    """

    if result.get("success"):
        return jsonify(result), 200
    code = result.get("error_code") or ""
    status = {"VALIDATION_ERROR": 400, "API_AUTH_FAILED": 503}.get(code, 502)
    return jsonify(result), status


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
