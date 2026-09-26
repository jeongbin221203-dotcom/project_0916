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


# --- 두 번 눌러도 한 번만 -----------------------------------------------------------
#
# 왜 필요한가
#   화면은 [만들기]를 누르는 순간 단추를 잠급니다. 그래도 두 번째 창에서 누르거나,
#   브라우저·중계 서버가 POST 를 다시 보내면 그대로 **두 건**이 만들어집니다.
#   넣어 보니 정말 두 건이 생겼습니다.
#
#   두 건이 생기면 둘 다 관세사에게 갈 수 있습니다. 같은 화물을 두 번 신고하거나,
#   한쪽만 고쳐 둔 채 다른 쪽이 나갑니다. 번호가 달라 사람은 알아채기 어렵습니다.
#
# 어떻게 하나
#   **보내 온 내용 전체**를 지문으로 만들어 잠깐 기억해 둡니다. 똑같은 내용이
#   다시 오면 새로 만들지 않고 앞서 만든 것을 그대로 돌려줍니다.
#
#   처음에는 "같은 사람·같은 스케줄·같은 바이어·같은 금액"처럼 몇 칸만 골라
#   견주었습니다. 그랬더니 **화물이 다른데도**(위험물 vs 일반) 같은 건으로
#   묶였습니다. 고른 칸에 화물이 없었기 때문입니다. 몇 칸만 보면 언제나
#   빠뜨린 칸이 생깁니다. 그래서 보낸 것을 통째로 봅니다. (2026-09-26)
ONCE_SECONDS = 90
ONCE_KEEP = 4               # 쿠키에 담기므로 조금만 기억합니다


def once_only(kind: str, payload) -> str:
    """같은 요청이 방금 또 왔으면 그때 만든 것을 돌려줍니다. 처음이면 빈 글자."""

    import hashlib
    import json as _json
    import time

    from flask import session

    try:
        body = _json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return ""
    key = f"{kind}:{hashlib.sha256(body.encode('utf-8')).hexdigest()[:32]}"
    now = time.time()
    seen = {k: v for k, v in (session.get("_once") or {}).items()
            if isinstance(v, list) and len(v) == 2 and now - v[1] < ONCE_SECONDS}
    session["_once"] = seen
    found = seen.get(key)
    return found[0] if found else ""


def remember_once(kind: str, payload, made: str) -> None:
    """만든 것을 지문과 함께 기억해 둡니다."""

    import hashlib
    import json as _json
    import time

    from flask import session

    try:
        body = _json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return
    key = f"{kind}:{hashlib.sha256(body.encode('utf-8')).hexdigest()[:32]}"
    now = time.time()
    seen = {k: v for k, v in (session.get("_once") or {}).items()
            if isinstance(v, list) and len(v) == 2 and now - v[1] < ONCE_SECONDS}
    seen[key] = [made, now]
    # 오래된 것부터 버립니다.
    if len(seen) > ONCE_KEEP:
        for old in sorted(seen, key=lambda k: seen[k][1])[:len(seen) - ONCE_KEEP]:
            seen.pop(old, None)
    session["_once"] = seen


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
