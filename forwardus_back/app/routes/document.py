"""Trade Document Center."""

from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for

from app.routes import load_shipment
from app.services import ServiceError, document_service
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
    )


@document_bp.post("/<shipment_id>/generate")
def generate(shipment_id: str):
    shipment = load_shipment(shipment_id)
    overwrite = request.form.get("overwrite") == "1"
    created = document_service.generate_documents(shipment, overwrite=overwrite)
    flash(f"{len(created)}개 문서를 Shipment 데이터로 작성했습니다." if created else "이미 모든 문서가 작성되어 있습니다.", "success")
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
        fields=document_service.document_view(document),
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
