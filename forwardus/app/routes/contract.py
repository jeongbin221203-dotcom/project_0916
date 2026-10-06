"""계약서 조항 점검 — 점검표·판정·문안 내보내기.

화면 두 곳이 같은 창구를 씁니다.
  무역 상담(/)          "계약서 조항 점검" 단추
  서류 수정(/documents/<id>/<doc_type>)  같은 칸

Shipment를 만들지 않고, **올린 파일도 남기지 않습니다.** 읽고 판정만 합니다.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request, Response

from app.processors import contract_clauses
from app.routes import error_response, json_body
from app.services import ServiceError, contract_clause_service
from app.validators import ValidationError

contract_bp = Blueprint("contract", __name__, url_prefix="/contract")

# 계약서는 서류보다 깁니다. 그래도 한도를 둡니다.
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
ALLOWED_SUFFIXES = (".pdf", ".docx", ".txt", ".md", ".png", ".jpg", ".jpeg", ".webp")
MAX_EXPORT_KEYS = 100


@contract_bp.get("/clauses")
def clauses():
    """이 건에 걸리는 조항 점검표. 인코텀즈를 주면 그에 맞춰 추립니다."""

    incoterms = (request.args.get("incoterms") or "").upper()
    # 도착국을 주면 그 나라에 흔한 조항을 앞세웁니다. 없어도 그대로 돕니다.
    country = (request.args.get("country") or "").upper()
    return jsonify({"success": True, "data": {
        "incoterms": incoterms,
        "country": country,
        "groups": contract_clause_service.checklist(incoterms, country=country),
        "country_watch": [row["key"] for row in
                          contract_clauses.for_country(country)] if country else [],
        "note": contract_clause_service.DISCLAIMER,
    }})


@contract_bp.post("/review")
def review():
    """올린 계약서(또는 붙여 넣은 글)를 읽어 판정합니다.

    파일이 오면 파일을, 아니면 본문(text)을 봅니다. AI를 부르지 않습니다.
    """

    # JSON 본문이 배열·숫자면 request.json.get 이 500 을 냈습니다(사용성 4회차) — json_body 는 늘 dict.
    payload = json_body() if request.is_json else {}
    incoterms = request.form.get("incoterms") or payload.get("incoterms") or ""
    # 도착국. 주면 그 나라에 흔한 독소조항을 앞세우고, 아직 안 보이는 것도
    # watch_country 로 미리 알려 줍니다. 없어도 판정은 그대로 돕니다. (2026-10-02)
    country = request.form.get("country") or payload.get("country") or ""
    upload = request.files.get("file")
    try:
        if upload is not None and (upload.filename or "").strip():
            name = upload.filename
            if not name.lower().endswith(ALLOWED_SUFFIXES):
                raise ValidationError(
                    "PDF·Word(docx)·사진·텍스트 파일만 읽을 수 있습니다. "
                    "한글(hwp)·옛 워드(doc)는 PDF로 저장해 올려 주세요.", "file")
            data = upload.stream.read(MAX_UPLOAD_BYTES + 1)
            if len(data) > MAX_UPLOAD_BYTES:
                raise ValidationError(
                    f"계약서는 {MAX_UPLOAD_BYTES // (1024 * 1024)}MB까지 읽습니다.", "file")
            text, notes = contract_clause_service.read_contract(name, data)
            if not text.strip():
                raise ServiceError(
                    "글자를 읽지 못했습니다. 스캔본이면 글자가 있는 PDF로 다시 저장하거나, "
                    "계약서 본문을 붙여 넣어 주세요.", "UNREADABLE")
        else:
            notes = []
            text = request.form.get("text") or payload.get("text") or ""
            if not isinstance(text, str):
                raise ValidationError("text 는 글자여야 합니다.", "text")
        result = contract_clause_service.review(text, str(incoterms or ""),
                                                str(country or ""))
        # 어디까지·어떻게 읽었는지(OCR·쪽 한도) — 상태줄에 붙입니다(사용성 점검 2회차).
        result["notes"] = notes + result.pop("review_notes", [])
    except (ValidationError, ServiceError) as exc:
        return error_response(exc)
    result["summary"] = contract_clause_service.as_text(result)
    # 판정 결과를 파일로 받을 수 있게 — 받는 파일이 넣을 문안뿐이었습니다(사용성 4회차).
    result["report"] = contract_clause_service.report_plain(result)
    return jsonify({"success": True, "data": result})


@contract_bp.post("/export")
def export():
    """고른 조항의 문안을 내려받습니다.

    format  docx  Word·한글에서 엽니다 (화면의 기본)
            txt   어디서든 열리는 평문
            md    예전 그대로 — format 을 안 주던 호출이 깨지지 않게 둡니다
    """

    payload = json_body()
    keys = payload.get("keys")
    # 같은 key 2,000개를 그대로 받아 17초가 걸렸습니다(사용성 4회차) — 겹친 것을 빼고 100개까지.
    keys = list(dict.fromkeys(str(k) for k in keys))[:MAX_EXPORT_KEYS] if isinstance(keys, list) else []
    kind = str(payload.get("format") or "md").lower()
    if kind not in EXPORT_FORMATS:
        return error_response(ValidationError("format 은 docx · txt · md 중 하나입니다.", "format"))
    build, mimetype = EXPORT_FORMATS[kind]
    try:
        body = build(keys)
    except (ValidationError, ServiceError) as exc:
        return error_response(exc)
    # mimetype 에 charset 을 넣으면 Flask 가 한 번 더 붙여 "charset=utf-8; charset=utf-8" 이 됐습니다.
    return Response(body, content_type=mimetype, headers={
        "Content-Disposition": f'attachment; filename="contract-clauses.{kind}"'})


EXPORT_FORMATS = {
    "docx": (contract_clause_service.clause_docx,
             "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    "txt": (contract_clause_service.clause_plain, "text/plain; charset=utf-8"),
    "md": (contract_clause_service.clause_text, "text/markdown; charset=utf-8"),
}
