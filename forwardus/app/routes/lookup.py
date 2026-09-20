"""관세청 조회 모음 화면."""

from __future__ import annotations

from flask import Blueprint, render_template, request

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


@lookup_bp.get("/sources")
def sources():
    """연결된 바깥 자료원 현황."""

    return render_template("lookup/sources.html", data=lookup_service.data_sources())


@lookup_bp.get("/sources/check")
def sources_check():
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
