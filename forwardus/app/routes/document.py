"""Trade Document Center."""

from __future__ import annotations

import io

from flask import (Blueprint, flash, jsonify, redirect, render_template,
                   request, send_file, url_for)

from app.routes import error_response, load_shipment
from app.routes.auth import current_user, login_required
from app.services import (ServiceError, customs_filing_service, document_extract_service,
                          document_service, document_start_service, draft_document_service,
                          requirement_service, shipment_service)
from app.validators import ValidationError

document_bp = Blueprint("document", __name__, url_prefix="/documents")


@document_bp.post("/draft/<kind>.pdf")
def draft_file(kind: str):
    """초안을 PDF로 내려받습니다.

    저장해 둔 것을 주는 게 아니라 그때그때 그려서 줍니다. 초안은 확정이
    아니라 서버에 남길 이유가 없습니다.
    """

    payload = request.get_json(silent=True) or {}
    # 은행 정보·바이어 주소는 브라우저가 따로(private) 보냅니다. 여기서만 합치고 버립니다.
    draft = draft_document_service.with_private(payload.get("draft") or {}, payload.get("private"))
    try:
        data = draft_document_service.pdf_bytes(kind, draft)
    except (ValidationError, ServiceError) as exc:
        return error_response(exc)
    return send_file(io.BytesIO(data), mimetype="application/pdf",
                     as_attachment=True,
                     download_name=draft_document_service.file_name(kind))


@document_bp.get("/new")
@login_required
def new():
    """서식이 요구하는 칸을 직접 채워 서류를 만드는 화면.

    예전에는 시작 화면 안에 있었는데, 홈은 대화하는 자리로 두고
    칸을 채우는 일은 이리로 옮겼습니다. 사이드바 "서류 작성"이 여기입니다.
    """

    return render_template("document/new.html",
                           checklist=document_start_service.checklist(),
                           recent=shipment_service.list_shipments(viewer=current_user())[:3])


@document_bp.post("/draft/preview")
def draft_preview():
    """검토 창에서 고친 값으로 미리보기를 다시 그립니다. 저장하지 않습니다."""

    payload = request.get_json(silent=True) or {}
    try:
        image = draft_document_service.preview_data(str(payload.get("kind") or ""),
                                                    payload.get("data"))
    except (ValidationError, ServiceError) as exc:
        return error_response(exc)
    return jsonify({"success": True, "data": {"preview": image}})


@document_bp.post("/draft/review.pdf")
def draft_review_pdf():
    """검토를 마친 서류들을 인쇄 규격(A4) PDF 한 파일로 내려받습니다.

    그리는 코드는 "PDF로 받기"와 같습니다(document_form). 서식이 한 곳에서 나와야
    화면의 미리보기와 인쇄물이 같은 모양이 됩니다.
    """

    payload = request.get_json(silent=True) or {}
    documents = payload.get("documents")
    try:
        data = draft_document_service.pdf_documents(documents)
    except (ValidationError, ServiceError) as exc:
        return error_response(exc)
    kinds = [str(row.get("kind")) for row in documents if isinstance(row, dict)]
    name = (draft_document_service.file_name(kinds[0]) if len(kinds) == 1
            else "trade_documents_draft.pdf")
    return send_file(io.BytesIO(data), mimetype="application/pdf", as_attachment=True,
                     download_name=name)


@document_bp.post("/extract")
def extract():
    """올린 B/L·Offer Sheet·견적서 등을 읽어 서류 작성 칸을 채울 초안을 돌려줍니다.

    Shipment를 만들지 않고, 파일도 남기지 않습니다. 확인과 만들기는 사람이 합니다.
    """

    upload = request.files.get("file")
    if upload is None or not upload.filename:
        return error_response(ServiceError("올릴 파일을 골라 주세요.", "VALIDATION_ERROR"))
    # 한도보다 한 바이트 더 읽어 보면, 큰 파일을 끝까지 읽지 않고도 넘친 것을 압니다.
    data = upload.stream.read(document_extract_service.MAX_UPLOAD_BYTES + 1)
    try:
        result = document_extract_service.extract(upload.filename, data)
    except (ValidationError, ServiceError) as exc:
        return error_response(exc)
    return jsonify({"success": True, "data": result})


@document_bp.post("/start")
@login_required
def start():
    """시작 화면에서 채운 내용으로 Shipment와 서류를 한 번에 만듭니다."""

    try:
        result = document_start_service.create(request.get_json(silent=True) or {},
                                               user_id=current_user().id)
    except (ValidationError, ServiceError) as exc:
        return error_response(exc)
    result["url"] = url_for("document.center", shipment_id=result["shipment_id"])
    return jsonify({"success": True, "data": result})


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


@document_bp.get("/<shipment_id>/origin-guide")
def origin_guide(shipment_id: str):
    """이 건에 쓸 수 있는 협정과 신청 창구. 시작 화면이 씁니다."""

    shipment = load_shipment(shipment_id)
    guide = document_service.origin_certificate_guide(shipment)
    return jsonify({"success": True, "data": {
        **guide,
        # 올린 서류는 그대로 넘길 수 없어 화면에 필요한 것만 추립니다.
        "uploads": [{"id": row.id, "filename": row.filename,
                     "agreement": row.agreement or "",
                     "status": row.review_status, "status_label": row.review_label,
                     "summary": row.review_summary or ""}
                    for row in guide["uploads"]],
        "upload_url": url_for("document.upload_requirement", shipment_id=shipment_id),
        "shipment_id": shipment.shipment_id,
    }})


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
        refund=customs_filing_service.refund_estimate(shipment),
    )


@document_bp.get("/<shipment_id>/customs-filing/clearance-code")
def api_clearance_code(shipment_id: str):
    """사업자등록번호로 통관고유부호를 찾아 줍니다."""

    load_shipment(shipment_id)
    result = customs_filing_service.lookup_clearance_code(request.args.get("business_no", ""))
    return jsonify(result), (200 if result["success"] else 502)


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
