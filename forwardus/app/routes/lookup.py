"""관세청 조회 모음 화면."""

from __future__ import annotations

from flask import Blueprint, abort, jsonify, render_template, request

from app.routes.auth import current_user, login_required_response
from app.services import ServiceError, lookup_service

lookup_bp = Blueprint("lookup", __name__, url_prefix="/lookup")


@lookup_bp.get("/")
def index():
    kind = request.args.get("kind", "")
    query = request.args.get("q", "")
    result, error = None, ""
    if kind and query.strip():
        try:
            result = lookup_service.run(kind, query)
        except ServiceError as exc:
            error = str(exc)
    return render_template(
        "lookup/index.html",
        catalog=lookup_service.catalog(),
        kind=kind or "shipping_company",
        query=query,
        result=result,
        error=error,
    )


@lookup_bp.get("/incoterms")
def incoterms():
    """인코텀즈 한눈에 보기. 조건을 눌러 비용·위험이 넘어가는 지점을 봅니다.

    내용은 운송 계획 화면이 쓰는 표(INCOTERMS_INFO)를 그대로 씁니다. 글을 두 벌로
    두면 한쪽만 고쳐집니다. 상담 답변에서 이 주소로 연결합니다.
    """

    from app.processors.cost_calculator import INCOTERMS_FLOW_STEPS, INCOTERMS_INFO

    return render_template("lookup/incoterms.html",
                           terms=INCOTERMS_INFO, flow=INCOTERMS_FLOW_STEPS)


@lookup_bp.get("/api/incoterms")
def api_incoterms():
    """11개 조건 자료. 홈 대화 답변 안의 표(incoterm_widget.js)가 한 번 받아 씁니다."""

    from app.processors.cost_calculator import INCOTERMS_FLOW_STEPS, INCOTERMS_INFO

    return jsonify({"success": True,
                    "data": {"terms": INCOTERMS_INFO, "steps": INCOTERMS_FLOW_STEPS}})


def _admin_only():
    """운영자 진단 화면 — 어떤 키가 설정돼 있는지 보이고, check 는 외부 API 를 실제로 부릅니다.
    로그인 없이 열려 있어 호출 한도를 소진시킬 수 있었습니다(전수 점검 1회차)."""

    denied = login_required_response()
    if denied is not None:
        abort(denied)
    viewer = current_user()
    if not (viewer and viewer.is_admin):
        abort(403)


@lookup_bp.get("/sources")
def sources():
    _admin_only()
    """연결된 바깥 자료원 현황."""

    return render_template("lookup/sources.html", data=lookup_service.data_sources())


@lookup_bp.get("/sources/check")
def sources_check():
    _admin_only()
    """연결된 API를 실제로 한 번씩 불러 봅니다. 시간이 좀 걸립니다."""

    return render_template("lookup/sources.html",
                           data=lookup_service.data_sources(),
                           health=lookup_service.health_check())


@lookup_bp.get("/declaration")
def declaration():
    """수출신고필증 검증. 여섯 항목을 모두 넣어야 대조합니다."""

    form = request.args.to_dict()
    result, error = None, ""
    if any(form.get(key) for key in ("publication_no", "declaration_no")):
        try:
            result = lookup_service.verify_declaration(form)
        except ServiceError as exc:
            error = str(exc)
    return render_template("lookup/declaration.html", form=form, result=result, error=error)
