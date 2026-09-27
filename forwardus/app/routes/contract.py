"""계약서 조항 점검 — 점검표·판정·문안 내보내기.

화면 두 곳이 같은 창구를 씁니다.
  무역 상담(/)          "계약서 조항 점검" 단추
  서류 수정(/documents/<id>/<doc_type>)  같은 칸

Shipment를 만들지 않고, **올린 파일도 남기지 않습니다.** 읽고 판정만 합니다.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request, Response

from app.routes import error_response, json_body
from app.services import ServiceError, contract_clause_service
from app.validators import ValidationError

contract_bp = Blueprint("contract", __name__, url_prefix="/contract")

# 계약서는 서류보다 깁니다. 그래도 한도를 둡니다.
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
ALLOWED_SUFFIXES = (".pdf", ".txt", ".md", ".png", ".jpg", ".jpeg", ".webp")


@contract_bp.get("/clauses")
def clauses():
    """이 건에 걸리는 조항 점검표. 인코텀즈를 주면 그에 맞춰 추립니다."""

    incoterms = (request.args.get("incoterms") or "").upper()
    return jsonify({"success": True, "data": {
        "incoterms": incoterms,
        "groups": contract_clause_service.checklist(incoterms),
        "note": contract_clause_service.DISCLAIMER,
    }})


@contract_bp.post("/review")
def review():
    """올린 계약서(또는 붙여 넣은 글)를 읽어 판정합니다.

    파일이 오면 파일을, 아니면 본문(text)을 봅니다. AI를 부르지 않습니다.
    """

    incoterms = (request.form.get("incoterms") or
                 (request.json or {}).get("incoterms") if request.is_json else
                 request.form.get("incoterms") or "")
    upload = request.files.get("file")
    try:
        if upload is not None and (upload.filename or "").strip():
            name = upload.filename
            if not name.lower().endswith(ALLOWED_SUFFIXES):
                raise ValidationError(
                    "PDF·사진·텍스트 파일만 읽을 수 있습니다. "
                    "한글(hwp)·워드는 PDF로 저장해 올려 주세요.", "file")
            data = upload.stream.read(MAX_UPLOAD_BYTES + 1)
            if len(data) > MAX_UPLOAD_BYTES:
                raise ValidationError(
                    f"계약서는 {MAX_UPLOAD_BYTES // (1024 * 1024)}MB까지 읽습니다.", "file")
            text = contract_clause_service.read_file(name, data)
            if not text.strip():
                raise ServiceError(
                    "글자를 읽지 못했습니다. 스캔본이면 글자가 있는 PDF로 다시 저장하거나, "
                    "계약서 본문을 붙여 넣어 주세요.", "UNREADABLE")
        else:
            text = (request.form.get("text") or
                    ((request.json or {}).get("text") if request.is_json else "") or "")
        result = contract_clause_service.review(text, str(incoterms or ""))
    except (ValidationError, ServiceError) as exc:
        return error_response(exc)
    result["summary"] = contract_clause_service.as_text(result)
    return jsonify({"success": True, "data": result})


@contract_bp.post("/export")
def export():
    """고른 조항의 문안을 텍스트 파일로 내려받습니다."""

    payload = json_body()
    keys = payload.get("keys")
    try:
        body = contract_clause_service.clause_text(keys if isinstance(keys, list) else [])
    except (ValidationError, ServiceError) as exc:
        return error_response(exc)
    return Response(body, mimetype="text/markdown; charset=utf-8", headers={
        "Content-Disposition": 'attachment; filename="contract-clauses.md"'})
