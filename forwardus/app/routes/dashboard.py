"""Dashboard — 상단의 Shipments 메뉴를 합친 자리. 권한에 따라 화면과 데이터 범위가 다릅니다.

마스터(role "master"/"admin")  전체 통합 Dashboard: 모든 사용자의 Shipment · 플랫폼 통계 ·
                               검색/필터 · 상태 강제 변경 · 엑셀(CSV) 내려받기
일반 회원(role "user")          내 Dashboard: 내 Shipment만 · 진행 현황 · 최근 서류 · 일정/B/L 요약

API도 같은 범위 규칙(dashboard_service)을 씁니다.
  GET  /api/dashboard                         보는 사람 범위의 요약 + 목록
  GET  /api/shipments                         보는 사람 범위의 Shipment 목록
  GET  /api/admin/shipments                   전체 목록 (마스터만, 아니면 403)
  POST /api/admin/shipments/<id>/status       상태 강제 변경 (마스터만, 아니면 403)
"""

from __future__ import annotations

from flask import Blueprint, Response, abort, flash, jsonify, redirect, render_template, request, url_for

from app.models.shipment import STATUS_LABELS
from app.routes import error_response, json_body
from app.routes.auth import current_user, login_required_response
from app.services import ServiceError, analytics_service, dashboard_service

dashboard_bp = Blueprint("dashboard", __name__, url_prefix="/dashboard")
dashboard_api_bp = Blueprint("dashboard_api", __name__, url_prefix="/api")


# 주소로 바로 들어온 경우에는 로그인 화면으로 보냈다가 다시 돌려보냅니다. (API는 401 JSON)
@dashboard_bp.before_request
@dashboard_api_bp.before_request
def require_login():
    return login_required_response()


def _filters() -> dict:
    return {"status": request.args.get("status") or None,
            "q": request.args.get("q", ""), "owner": request.args.get("owner", "")}


def _number(name: str, default: int) -> int:
    """주소에서 숫자 하나를 읽습니다. 사람이 주소를 고쳐 넣어도 터지지 않아야 합니다."""

    try:
        return int(request.args.get(name, default))
    except (TypeError, ValueError):
        return default


@dashboard_bp.get("")
def index():
    viewer = current_user()
    filters = _filters()
    owners = dashboard_service.owner_emails() if viewer.is_admin else None
    shipments = dashboard_service.search(viewer, owners=owners, **filters)
    common = {"viewer": viewer, "shipments": shipments, "filters": filters,
              "statuses": STATUS_LABELS, **analytics_service.build_dashboard(viewer)}
    if viewer.is_admin:
        # 표만 쪽으로 나눕니다. 위의 통계 칸과 CSV는 거른 목록 전체를 그대로 씁니다.
        page = dashboard_service.paginate(
            shipments, _number("page", 1), _number("size", dashboard_service.PAGE_SIZE))
        return render_template("dashboard/master.html", owners=owners, page=page,
                               sizes=dashboard_service.PAGE_SIZES,
                               default_size=dashboard_service.PAGE_SIZE,
                               stats=dashboard_service.platform_stats(viewer), **common)
    mine = dashboard_service.search(viewer)          # 요약 칸은 거르기 전 내 전체로 셉니다
    return render_template("dashboard/personal.html",
                           mine=dashboard_service.personal(viewer, mine), **common)


@dashboard_bp.post("/admin/shipments/<shipment_id>/status")
def admin_status(shipment_id: str):
    """마스터가 목록에서 바로 상태를 바꿉니다."""

    viewer = current_user()
    if not viewer.is_admin:
        abort(403)
    try:
        shipment = dashboard_service.force_status(viewer, shipment_id, request.form.get("status", ""))
        flash(f"{shipment.shipment_id} 상태를 '{shipment.status_label}'(으)로 바꿨습니다.", "success")
    except ServiceError as exc:
        flash(str(exc), "error")
    return redirect(request.form.get("back") if _safe_back(request.form.get("back"))
                    else url_for("dashboard.index"))


def _safe_back(target: str | None) -> bool:
    return bool(target) and target.startswith("/dashboard") and not target.startswith("//")


@dashboard_bp.get("/admin/export.csv")
def admin_export():
    """지금 거른 목록 그대로 엑셀(CSV)로 내려받습니다."""

    viewer = current_user()
    if not viewer.is_admin:
        abort(403)
    owners = dashboard_service.owner_emails()
    shipments = dashboard_service.search(viewer, owners=owners, **_filters())
    data = dashboard_service.export_csv(viewer, shipments, owners)
    return Response(data, mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": "attachment; filename=forwardus_shipments.csv"})


# --- API --------------------------------------------------------------------------

@dashboard_api_bp.get("/dashboard")
def api_dashboard():
    viewer = current_user()
    owners = dashboard_service.owner_emails() if viewer.is_admin else None
    shipments = dashboard_service.search(viewer, owners=owners, **_filters())
    data = {"role": viewer.role, "scope": dashboard_service.scope_of(viewer),
            "cards": dashboard_service.status_cards(shipments),
            "shipments": [dashboard_service.shipment_row(s, owners) for s in shipments]}
    if viewer.is_admin:
        stats = dashboard_service.platform_stats(viewer)
        data["stats"] = {key: stats[key] for key in
                         ("active", "total", "users", "month_quotes", "month_documents")}
    return jsonify({"success": True, "data": data})


@dashboard_api_bp.get("/shipments")
def api_shipments():
    viewer = current_user()
    owners = dashboard_service.owner_emails() if viewer.is_admin else None
    shipments = dashboard_service.search(viewer, owners=owners, **_filters())
    return jsonify({"success": True, "scope": dashboard_service.scope_of(viewer),
                    "data": [dashboard_service.shipment_row(s, owners) for s in shipments]})


@dashboard_api_bp.get("/admin/shipments")
def api_admin_shipments():
    viewer = current_user()
    try:
        dashboard_service.require_admin(viewer)
    except ServiceError as exc:
        return error_response(exc)
    owners = dashboard_service.owner_emails()
    shipments = dashboard_service.search(viewer, owners=owners, **_filters())
    return jsonify({"success": True, "scope": "all",
                    "data": [dashboard_service.shipment_row(s, owners) for s in shipments]})


@dashboard_api_bp.post("/admin/shipments/<shipment_id>/status")
def api_admin_status(shipment_id: str):
    payload = json_body()
    try:
        shipment = dashboard_service.force_status(current_user(), shipment_id,
                                                  str(payload.get("status") or ""))
    except ServiceError as exc:
        return error_response(exc)
    return jsonify({"success": True, "data": dashboard_service.shipment_row(shipment)})
