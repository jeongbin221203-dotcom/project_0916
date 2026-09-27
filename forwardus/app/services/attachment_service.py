"""시작 화면 적는 칸의 `+`로 붙인 파일 하나와, 같이 적은 말 한 줄을 받아 처리합니다.

세 탭(무역 상담 · 운송 계획 · 서류 작성)이 같은 창구를 씁니다.

1. 어떤 서류인지 먼저 알아봅니다. 사람이 무엇을 올릴지 미리 알 수 없습니다.
   (B/L일 수도, Offer Sheet일 수도, 견적서일 수도 있습니다)
2. 같이 적은 말이 "이거 기반으로 서류 만들어줘", "인보이스 써줘"처럼 서류를
   만들어 달라는 말이면, 어느 탭에서 올렸든 서류 작성으로 보냅니다(route).
   서류 작성 탭에서 올렸으면 말이 없어도 서류 작성입니다.
3. 서류 작성이면 빠진 필수 정보를 짚어 묻는 흐름(document_pipeline_service)을 시작합니다.
   그렇지 않으면 읽은 값을 곁들여 상담 답을 드립니다.

탭을 옮길지는 AI가 아니라 규칙(document_pipeline_service.intent)이 정합니다.
같은 말에는 늘 같게 움직여야 사람이 믿고 씁니다.
"""

from __future__ import annotations

from app.services import (ServiceError, contract_clause_service,
                          document_extract_service,
                          document_pipeline_service as pipe, support_chat_service)

MODES = ("consult", "planning", "documents")
# 상담에 곁들이는 서류 내용. 질문 한도(2,000자) 안에 사람이 적은 말이 들어갈 자리를 남깁니다.
MAX_CONTEXT = 1_000


def context(document: dict, filename: str = "") -> str:
    """상담 AI에게 건넬 '올린 서류' 설명. 읽은 값만 적습니다. (짐작한 값은 없습니다)"""

    lines = [f"[사용자가 첨부한 서류] {document.get('document_label') or '무역 서류'}"
             + (f" · 파일 {filename}" if filename else "")]
    lines += [f"- {row['label']}: {row['value']}" for row in document.get("summary") or []]
    items = (document.get("form") or {}).get("items") or []
    for no, row in enumerate(items[:5], 1):
        parts = [row.get("product_description"), row.get("quantity") and f"{row['quantity']} PKG",
                 row.get("unit_price") and f"단가 {row['unit_price']}",
                 row.get("hs_code") and f"HS {row['hs_code']}"]
        lines.append(f"- 품목 {no}: " + " / ".join(part for part in parts if part))
    if document.get("missing"):
        lines.append("- 비어 있는 필수 칸: " + ", ".join(document["missing"][:8]))
    text = "\n".join(lines)
    return text[:MAX_CONTEXT]


def handle(filename: str, data: bytes, *, message: str = "", mode: str = "consult",
           history: list | None = None) -> dict:
    """파일을 읽어 종류를 알리고, 탭과 적은 말에 맞춰 다음 일을 합니다."""

    mode = mode if mode in MODES else "consult"
    message = str(message or "").strip()
    if len(message) > pipe.MAX_MESSAGE:
        raise ServiceError(f"{pipe.MAX_MESSAGE:,}자 아래로 줄여 주세요.", "VALIDATION_ERROR")

    # 계약서를 붙였으면 **조항으로 답합니다.**
    #
    # 계약서는 무역 서류가 아닙니다. 그대로 서류 읽기에 넣으면 AI가 송장인 줄
    # 알고 엉뚱한 칸을 채우거나, "읽을 값이 없습니다"로 끝납니다. 정작 알고
    # 싶은 것은 빠진 조항과 위험한 조항인데 그 말이 아예 안 나옵니다.
    # 글자만 먼저 읽어 계약서인지 보고, 맞으면 AI를 부르지 않고 판정합니다.
    # (그래서 키가 없어도 됩니다) (2026-09-26)
    judged = _contract_answer(filename, data, message)
    if judged is not None:
        return judged

    document = document_extract_service.extract(filename, data)
    label = document["document_label"]
    wish = pipe.intent(message)
    result = {
        "document": document,
        "recognized": f"이 문서는 **{label}**입니다.",
        "intent": wish,
    }

    if wish["make"] or mode == "documents":
        result["route"] = "documents"
        result["pipeline"] = pipe.start({"form": document["form"], "document_label": label,
                                         "kinds": wish["kinds"]})
        return result

    result["route"] = mode
    if not message:
        return result
    # 올린 서류에 대해 묻는 말입니다. 서류에서 읽은 값을 곁들여 상담으로 답합니다.
    question = context(document, filename) + "\n\n[질문] " + message
    answer = support_chat_service.ask(question, history or [])
    result["question"] = question
    if answer["success"]:
        result["answer"] = answer["data"]["answer"]
    else:
        # 서류는 읽었으니 실패로 돌려보내지 않습니다. 읽은 결과는 보여 주고 답만 다시 묻게 합니다.
        result["answer_error"] = answer.get("message") or "답을 받지 못했습니다."
    return result


def _contract_answer(filename: str, data: bytes, message: str) -> dict | None:
    """붙인 파일이 계약서면 조항 판정을, 아니면 None을 돌려줍니다.

    읽다가 잘못되면 조용히 None을 냅니다. 계약서가 아닐 때 여기서 막히면
    멀쩡한 서류까지 못 읽게 됩니다.
    """

    # 읽다가 잘못되면 **조용히 넘어갑니다.** 계약서가 아닐 때 여기서 막히면
    # 멀쩡한 서류까지 못 읽게 됩니다. (깨진 PDF 하나에 서류 읽기가 통째로 멈췄습니다)
    try:
        text = contract_clause_service.read_file(filename, data)
    except Exception:                                   # noqa: BLE001
        text = ""
    if not (text and contract_clause_service.looks_like_contract(text)):
        _refuse_plain_text(filename)
        return None
    result = contract_clause_service.review(text)
    return {
        "document": {"document_type": "contract", "document_label": "계약서",
                     "form": {"fields": {}, "items": []}, "summary": [], "missing": [],
                     "notes": [], "hs_queries": [], "filled": 0, "source": "contract"},
        "recognized": "이 문서는 **계약서**입니다. 서류 칸을 채우는 대신 "
                      "**조항을 살펴봤습니다.**",
        "intent": {"make": False, "kinds": []},
        "route": "consult",
        "answer": contract_clause_service.as_text(result),
        "contract": {key: result[key] for key in ("missing", "toxic", "gain", "present")},
        "question": message or filename,
    }


def _refuse_plain_text(filename: str) -> None:
    """글자 파일인데 계약서가 아니면 여기서 밝힙니다.

    txt·md는 계약서를 보시려고 받는 것입니다. 그대로 서류 읽기로 넘기면
    "올릴 수 있는 형식은 pdf, png…"라는 엉뚱한 말이 나옵니다.
    """

    if not str(filename or "").lower().endswith((".txt", ".md")):
        return
    raise ServiceError(
        "글자 파일(TXT·MD)은 **계약서 조항을 살펴볼 때만** 받습니다. "
        "계약서라면 조항이 보이게 전문을 넣어 주시고, 무역 서류(B/L·송장·"
        "오퍼시트)라면 PDF나 사진으로 올려 주세요.", "VALIDATION_ERROR")
