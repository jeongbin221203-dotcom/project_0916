"""Trade Document Center."""

from __future__ import annotations

import io

from flask import (Blueprint, flash, jsonify, redirect, render_template,
                   request, send_file, url_for)

from app.extensions import db
from app.routes import error_response, load_shipment
from app.routes.auth import current_user, login_required
from app.services import (ServiceError, customs_filing_service, document_draft_service,
                          document_extract_service, document_service, document_source_service,
                          document_start_service, draft_document_service, requirement_service,
                          shipment_service, translate_service)
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


@document_bp.get("/blank/<kind>.pdf")
def blank_file(kind: str):
    """빈 서식(상업송장·패킹리스트) PDF를 바로 내려받습니다. 로그인하지 않아도 됩니다."""

    try:
        data = draft_document_service.blank_pdf(kind)
    except ServiceError as exc:
        return error_response(exc)
    return send_file(io.BytesIO(data), mimetype="application/pdf", as_attachment=True,
                     download_name=draft_document_service.blank_file_name(kind))


@document_bp.get("/new")
@login_required
def new():
    """서식이 요구하는 칸을 직접 채워 서류를 만드는 화면.

    예전에는 시작 화면 안에 있었는데, 홈은 대화하는 자리로 두고
    칸을 채우는 일은 이리로 옮겼습니다. 사이드바 "서류 작성"이 여기입니다.
    """

    # Shipment 화면에서 넘어왔으면 돌아갈 자리를 알려 줍니다. 없으면 브라우저
    # 뒤로가기밖에 없는데, 칸을 채우다 누르면 적던 것이 날아갑니다.
    back_id = (request.args.get("back") or "").strip()
    back = None
    if back_id:
        try:
            # 볼 권한이 있는 건만. 남의 건 번호를 주소에 적어 넣어도 열리지 않습니다.
            found = shipment_service.get_or_404(back_id, viewer=current_user())
        except ServiceError:
            found = None
        if found:
            back = {"shipment_id": found.shipment_id, "project_name": found.project_name,
                    "url": url_for("document.center", shipment_id=found.shipment_id)}

    return render_template("document/new.html",
                           checklist=document_start_service.checklist(),
                           sources=document_source_service.list_sources(current_user()),
                           back=back,
                           recent=shipment_service.list_shipments(viewer=current_user())[:3])


@document_bp.get("/api/sources/<kind>/<source_id>")
@login_required
def source_values(kind: str, source_id: str):
    """고른 건의 칸 값을 돌려줍니다. 화면이 서류 작성 칸을 채우는 데 씁니다.

    목록은 화면을 그릴 때 함께 내려보내므로(new.html) 따로 부르지 않습니다.
    값은 고른 뒤에만 필요해서 여기서 받습니다.
    """

    try:
        return jsonify({"success": True,
                        "data": document_source_service.load(current_user(), kind, source_id)})
    except (ValidationError, ServiceError) as exc:
        return error_response(exc)


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


@document_bp.post("/suggest-name")
def suggest_name():
    """견적명 자동 제안. 화면이 자리표시로 보여 주고, 비우면 서버가 같은 이름을 씁니다.

    이름 짓는 규칙을 화면에 두면 제안한 이름과 저장되는 이름이 어긋납니다.
    규칙은 document_defaults.project_name 한 곳에만 둡니다.
    """

    payload = request.get_json(silent=True) or {}
    items = payload.get("items")
    name = document_start_service.suggest_project_name(
        payload, items if isinstance(items, list) else [])
    return jsonify({"success": True, "data": {"project_name": name}})


@document_bp.post("/draft/save")
@login_required
def save_draft():
    """검토 창에서 적은 견적명과 서류 값을 저장합니다.

    **Shipment를 만들지 않습니다.** 스케줄을 고르기 전에도, 서류부터 먼저
    쓰더라도 사람이 지은 이름이 남아야 합니다. 대시보드는 이 줄을
    "작성 중인 서류"로 보여 줍니다. (document_draft_service)
    """

    try:
        data = document_draft_service.save(current_user(), request.get_json(silent=True) or {})
    except (ValidationError, ServiceError) as exc:
        return error_response(exc)
    return jsonify({"success": True, "data": data})


@document_bp.patch("/draft/<int:draft_id>/title")
@login_required
def rename_draft(draft_id: int):
    """견적명만 고칩니다. 검토 창에서 이름 칸을 벗어날 때 부릅니다."""

    payload = request.get_json(silent=True) or {}
    try:
        data = document_draft_service.rename(current_user(), draft_id,
                                             str(payload.get("quote_title") or ""))
    except (ValidationError, ServiceError) as exc:
        return error_response(exc)
    return jsonify({"success": True, "data": data})


@document_bp.delete("/draft/<int:draft_id>")
@login_required
def delete_draft(draft_id: int):
    try:
        document_draft_service.delete(current_user(), draft_id)
    except (ValidationError, ServiceError) as exc:
        return error_response(exc)
    return jsonify({"success": True})


@document_bp.post("/start")
@login_required
def start():
    """시작 화면에서 채운 내용으로 Shipment와 서류를 한 번에 만듭니다.

    draft_id가 함께 오면 그 초안을 승격합니다. 사람이 검토 창에서 지은
    견적명을 그대로 가져오고, 만든 뒤 그 초안을 이 Shipment에 잇습니다.
    """

    viewer = current_user()
    payload = request.get_json(silent=True) or {}
    draft_id = payload.get("draft_id")
    if draft_id and not str(payload.get("project_name") or "").strip():
        # 화면이 이름을 따로 안 보냈으면 초안에 적어 둔 이름을 씁니다.
        payload = {**payload,
                   "project_name": document_draft_service.title_of(viewer, draft_id)}
    try:
        result = document_start_service.create(payload, user_id=viewer.id)
    except (ValidationError, ServiceError) as exc:
        return error_response(exc)
    if draft_id:
        document_draft_service.promote(viewer, draft_id,
                                       shipment_service.get_or_404(result["shipment_id"],
                                                                   viewer=viewer))
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


@document_bp.get("/api/required-docs")
@login_required
def api_required_docs():
    """HS부호만으로 필요한 서류를 미리 봅니다. (건을 만들기 전)

    서류 작성 화면에서 품목의 HS부호를 적으면 바로 이 목록이 뜹니다. 인증은 몇 주에서
    몇 달이 걸리는 것이라, 건을 만든 뒤에 알려 주면 이미 늦습니다.
    """

    from app.services import required_docs_service

    codes = [code for code in request.args.getlist("hs") if code.strip()]
    products = [name for name in request.args.getlist("product") if name.strip()]
    country = (request.args.get("country") or "").strip().upper()[:2]
    if not codes and not products:
        return error_response(ServiceError("HS부호나 품명을 알려주세요.",
                                           "VALIDATION_ERROR"))
    data = required_docs_service.preview(
        codes, country, request.args.get("country_name", ""), products,
        dangerous=request.args.get("dangerous") == "1",
        use_ai=request.args.get("ai", "1") != "0")
    return jsonify({"success": True, "data": {
        **data, "hs_codes": codes, "country": country,
        "upload_url": "", "filing_url": "",
    }})


@document_bp.get("/<shipment_id>/required-docs")
def required_docs(shipment_id: str):
    """이 건에 필요한 서류 한 목록. 서류 작성 화면의 '기타 필수 서류'가 씁니다.

    HS부호와 도착국으로 관세청 요건·우리 규칙·FTA·도착국 인증을 모으고,
    거기서 못 잡은 것만 AI가 보탭니다. (?ai=0 이면 AI를 부르지 않습니다)
    """

    from app.services import required_docs_service

    shipment = load_shipment(shipment_id)
    use_ai = request.args.get("ai", "1") != "0"
    data = required_docs_service.collect(shipment, use_ai=use_ai)
    return jsonify({"success": True, "data": {
        **data,
        "shipment_id": shipment.shipment_id,
        "destination": shipment.destination_name or shipment.destination_code or "",
        "upload_url": url_for("document.upload_requirement", shipment_id=shipment_id),
        "filing_url": url_for("document.customs_filing", shipment_id=shipment_id),
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


@document_bp.post("/<shipment_id>/requirements/hs-code")
def set_hs_code(shipment_id: str):
    """품목의 HS부호를 여기서 바로 적습니다.

    왜 여기에 두나
      이 화면은 "HS부호를 입력하면 이 품목에 걸린 요건을 짚어 드립니다"라고
      안내하면서, 정작 **적을 자리를 주지 않았습니다.** 어디로 가야 하는지도
      알려 주지 않아서, 안내를 읽고도 아무것도 할 수 없었습니다.

      HS부호가 비어 있으면 수출요건도 필수 서류도 전부 빈 채로 나옵니다.
      그 상태로 상담에 물으면 "확인할 요건이 없습니다"라고 답하기까지 했습니다.
      그러니 이 화면에서 바로 적을 수 있어야 합니다.
    """

    shipment = load_shipment(shipment_id)
    line_no = request.form.get("line_no", "1")
    raw = (request.form.get("hs_code") or "").strip()
    digits = "".join(ch for ch in raw if ch.isdigit())

    try:
        index = int(line_no) - 1
        cargo = shipment.cargos[index]
    except (ValueError, IndexError):
        flash("어느 품목인지 찾지 못했습니다.", "error")
        return redirect(url_for("document.requirements", shipment_id=shipment_id))

    # 지우는 것도 허용합니다. 잘못 적었으면 비우고 다시 적을 수 있어야 합니다.
    if raw and len(digits) not in (6, 10):
        flash("HS부호는 6자리(국제 공통) 또는 10자리(한국 HSK)입니다. "
              f"적어 주신 것은 {len(digits)}자리입니다.", "error")
        return redirect(url_for("document.requirements", shipment_id=shipment_id))

    cargo.hs_code = digits
    db.session.commit()
    flash(f"품목 {line_no}의 HS부호를 {digits or '(비움)'}으로 적었습니다."
          if digits else f"품목 {line_no}의 HS부호를 비웠습니다.", "success")
    return redirect(url_for("document.requirements", shipment_id=shipment_id))


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
        languages=translate_service.LANGUAGES,
        translate_ready=translate_service.available(),
        missing_summary=customs_filing_service.describe_missing(sheet),
        refund=customs_filing_service.refund_estimate(shipment),
    )


@document_bp.get("/<shipment_id>/customs-filing/clearance-code")
def api_clearance_code(shipment_id: str):
    """사업자등록번호로 통관고유부호를 찾아 줍니다."""

    load_shipment(shipment_id)
    result = customs_filing_service.lookup_clearance_code(request.args.get("business_no", ""))
    return jsonify(result), (200 if result["success"] else 502)


@document_bp.post("/<shipment_id>/customs-filing/translate")
def api_translate_filing(shipment_id: str):
    """그대로 보내기 글을 바이어의 언어로 옮깁니다. 저장하지 않습니다."""

    load_shipment(shipment_id)
    payload = request.get_json(silent=True) or {}
    try:
        data = translate_service.translate(str(payload.get("text") or ""),
                                           str(payload.get("language") or ""))
    except (ValidationError, ServiceError) as exc:
        return error_response(exc)
    return jsonify({"success": True, "data": data})


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
    # 확정한 서류는 다시 만들지 않습니다. 건너뛴 것을 이름으로 알려 줍니다.
    locked = document_service.locked_documents(shipment)
    created = document_service.generate_documents(shipment, overwrite=overwrite)
    flash(f"{len(created)}개 문서를 Shipment 데이터로 작성했습니다."
          if created else "이미 모든 문서가 최신 서식으로 작성되어 있습니다.", "success")
    if locked:
        flash(f"확정한 서류는 그대로 두었습니다: {', '.join(locked)}. "
              "새 내용으로 바꾸려면 그 서류를 열어 고치세요. (확정이 풀립니다)", "info")
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
        # 몇 건인지만 알리면 무엇을 고쳐야 하는지 찾아 내려가야 합니다.
        # 한 건이면 그 내용을 바로 적고, 여러 건이면 첫 건을 적고 나머지 수를 붙입니다.
        findings = result["findings"]
        first = findings[0].get("message", "")
        more = f" (그 밖에 {len(findings) - 1}건 더)" if len(findings) > 1 else ""
        flash(f"확인이 필요합니다 — {first}{more}", "error")
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
        # 확정(final)한 뒤에도 [수정하기]로 편집 모드에 들어옵니다.
        # 저장하면 확정이 풀리고 다시 검증을 거칩니다. (document_service.update_document)
        edit=request.args.get("edit") == "1",
    )


@document_bp.post("/<shipment_id>/<doc_type>")
def update(shipment_id: str, doc_type: str):
    shipment = load_shipment(shipment_id)
    try:
        # 확정한 서류를 고쳤는지는 저장하기 전 status로 압니다. 저장하면 generated로 돌아갑니다.
        was_final = document_service.get_document(shipment, doc_type).status == "final"
        document_service.update_document(shipment, doc_type, request.form.to_dict())
        flash("확정을 풀고 저장했습니다. 다시 검증하면 확정할 수 있습니다." if was_final
              else "문서를 저장했습니다. 변경 내용은 다시 검증해주세요.", "success")
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
