"""Trade Document Center."""

from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for

from app.routes import load_shipment
from app.services import (ServiceError, customs_filing_service, document_service,
                          requirement_service)
from app.validators import ValidationError

document_bp = Blueprint("document", __name__, url_prefix="/documents")


@document_bp.get("/<shipment_id>")
def center(shipment_id: str):
    shipment = load_shipment(shipment_id)
    return render_template(
        "document/center.html",
        shipment=shipment,
        documents=document_service.list_documents(shipment),
        validation=document_service.check_documents(shipment),
        origin_certificate=document_service.origin_certificate_guide(shipment),
    )


@document_bp.get("/<shipment_id>/requirements")
def requirements(shipment_id: str):
    """HS부호로 짚어 본 수출요건과 올려 둔 증빙 서류."""

    shipment = load_shipment(shipment_id)
    return render_template(
        "document/requirements.html",
        shipment=shipment,
        check=requirement_service.requirements_for(shipment),
    )


@document_bp.post("/<shipment_id>/requirements/upload")
def upload_requirement(shipment_id: str):
    shipment = load_shipment(shipment_id)
    try:
        document = requirement_service.upload(
            shipment, request.files.get("file"), request.form.get("requirement_key", ""),
            request.form.get("agreement", ""))
        # 올리자마자 읽어 이 건과 맞는지 봅니다. 키가 없으면 그렇다고 알려 줍니다.
        requirement_service.analyze(shipment, document.id)
        flash(f"{document.filename}을(를) 올렸습니다.", "success")
        if document.requirement_key == "origin":
            return redirect(url_for("document.center", shipment_id=shipment_id))
    except ValidationError as error:
        flash(str(error), "error")
        if request.form.get("requirement_key") == "origin":
            return redirect(url_for("document.center", shipment_id=shipment_id))
    return redirect(url_for("document.requirements", shipment_id=shipment_id))


@document_bp.post("/<shipment_id>/requirements/<int:document_id>/analyze")
def analyze_requirement(shipment_id: str, document_id: int):
    shipment = load_shipment(shipment_id)
    key = ""
    try:
        key = requirement_service.analyze(shipment, document_id).requirement_key
    except ServiceError as error:
        flash(str(error), "error")
    return redirect(_back_to(shipment_id, key))


@document_bp.post("/<shipment_id>/requirements/<int:document_id>/delete")
def delete_requirement(shipment_id: str, document_id: int):
    shipment = load_shipment(shipment_id)
    key = ""
    try:
        key = requirement_service.requirement_key_of(shipment, document_id)
        requirement_service.delete_upload(shipment, document_id)
        flash("올린 서류를 지웠습니다.", "success")
    except ServiceError as error:
        flash(str(error), "error")
    return redirect(_back_to(shipment_id, key))


def _back_to(shipment_id: str, requirement_key: str) -> str:
    """원산지증명서는 서류 센터에서 다루므로 온 자리로 돌려보냅니다."""

    page = "document.center" if requirement_key == "origin" else "document.requirements"
    return url_for(page, shipment_id=shipment_id)


@document_bp.get("/<shipment_id>/customs-filing")
def customs_filing(shipment_id: str):
    """관세사에게 넘길 수출신고 자료."""

    shipment = load_shipment(shipment_id)
    sheet = customs_filing_service.filing_sheet(shipment)
    return render_template(
        "document/customs_filing.html",
        shipment=shipment,
        sheet=sheet,
        sheet_text=customs_filing_service.as_text(sheet),
        missing_summary=customs_filing_service.describe_missing(sheet),
    )


@document_bp.post("/<shipment_id>/customs-filing")
def save_customs_filing(shipment_id: str):
    """신고 자료에만 쓰는 칸(사업자등록번호·거래구분·결제방법·원산지)을 저장합니다."""

    shipment = load_shipment(shipment_id)
    try:
        customs_filing_service.update_filing_fields(shipment, request.form)
        flash("신고 자료를 저장했습니다.", "success")
    except ValidationError as error:
        flash(str(error), "error")
    return redirect(url_for("document.customs_filing", shipment_id=shipment_id))


@document_bp.post("/<shipment_id>/generate")
def generate(shipment_id: str):
    shipment = load_shipment(shipment_id)
    overwrite = request.form.get("overwrite") == "1"
    created = document_service.generate_documents(shipment, overwrite=overwrite)
    flash(f"{len(created)}개 문서를 Shipment 데이터로 작성했습니다."
          if created else "이미 모든 문서가 최신 서식으로 작성되어 있습니다.", "success")
    return redirect(url_for("document.center", shipment_id=shipment_id))


@document_bp.post("/<shipment_id>/validate")
def validate(shipment_id: str):
    shipment = load_shipment(shipment_id)
    try:
        result = document_service.validate_shipment_documents(shipment)
    except ServiceError as exc:
        flash(str(exc), "error")
        return redirect(url_for("document.center", shipment_id=shipment_id))
    if result["status"] == "passed":
        flash("모든 문서의 주요 필드가 일치합니다.", "success")
    else:
        flash(f"{len(result['findings'])}건의 불일치가 발견되었습니다.", "error")
    return redirect(url_for("document.center", shipment_id=shipment_id) + "#validation")


@document_bp.get("/<shipment_id>/<doc_type>")
def view(shipment_id: str, doc_type: str):
    shipment = load_shipment(shipment_id)
    try:
        document = document_service.get_document(shipment, doc_type)
    except ServiceError:
        return redirect(url_for("document.center", shipment_id=shipment_id))
    return render_template(
        "document/view.html",
        shipment=shipment,
        document=document,
        sections=document_service.document_sections(document),
        items=document_service.document_items(document),
        edit=request.args.get("edit") == "1" and document.status != "final",
    )


@document_bp.post("/<shipment_id>/<doc_type>")
def update(shipment_id: str, doc_type: str):
    shipment = load_shipment(shipment_id)
    try:
        document_service.update_document(shipment, doc_type, request.form.to_dict())
        flash("문서를 저장했습니다. 변경 내용은 다시 검증해주세요.", "success")
    except (ValidationError, ServiceError) as exc:
        flash(str(exc), "error")
        return redirect(url_for("document.view", shipment_id=shipment_id, doc_type=doc_type, edit=1))
    return redirect(url_for("document.view", shipment_id=shipment_id, doc_type=doc_type))


@document_bp.post("/<shipment_id>/<doc_type>/finalize")
def finalize(shipment_id: str, doc_type: str):
    shipment = load_shipment(shipment_id)
    try:
        document_service.finalize_document(shipment, doc_type)
        flash("문서를 확정했습니다.", "success")
    except (ValidationError, ServiceError) as exc:
        flash(str(exc), "error")
    return redirect(url_for("document.view", shipment_id=shipment_id, doc_type=doc_type))
