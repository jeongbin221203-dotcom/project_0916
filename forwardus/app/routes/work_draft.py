"""작성 중인 수출 건 — 서류 작성과 운송 계획이 같이 쓰는 초안의 창구.

  GET    /api/work-draft            저장된 초안 (없으면 data: {})
  PUT    /api/work-draft            서류 작성에서 적은 값 저장 {fields, items, source}
  DELETE /api/work-draft            비우기
  GET    /api/work-draft/planning   운송 계획 화면이 칸을 미리 채울 모양
로그인한 회원 것만 읽고 씁니다. (로그인 전이면 401)
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.routes import error_response
from app.routes.auth import current_user, login_required_response
from app.services import ServiceError, work_draft_service

work_draft_bp = Blueprint("work_draft", __name__, url_prefix="/api/work-draft")


@work_draft_bp.before_request
def require_login():
    return login_required_response()


@work_draft_bp.get("")
def show():
    return jsonify({"success": True, "data": work_draft_service.load(current_user())})


@work_draft_bp.put("")
def save():
    payload = request.get_json(silent=True) or {}
    try:
        data = work_draft_service.save(current_user(), payload, str(payload.get("source") or ""))
    except ServiceError as exc:
        return error_response(exc)
    return jsonify({"success": True, "data": data})


@work_draft_bp.delete("")
def clear():
    work_draft_service.clear(current_user())
    return jsonify({"success": True})


@work_draft_bp.get("/planning")
def planning():
    return jsonify({"success": True, "data": work_draft_service.planning_prefill(current_user())})
