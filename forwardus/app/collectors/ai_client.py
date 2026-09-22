"""업로드한 증빙 서류를 AI로 읽어 이 건과 맞는지 봅니다.

우리가 직접 "이 서류는 적격"이라고 판정하지는 않습니다. 증명서의 적격 여부는
결국 세관과 수입국이 정합니다. 여기서 하는 일은 서류에 적힌 내용이 이 건의
품명·HS부호·수출자·수량과 어긋나지 않는지 대조해 주는 것입니다.

키는 AI_API_KEY 환경변수에서 읽습니다. 키가 없으면 분석하지 않고 그렇다고
알려 줍니다. (없는 결과를 지어내지 않습니다)
"""

from __future__ import annotations

import json

from app.collectors.base_client import fail, get_config, ok, request_text

OPENAI_URL = "https://api.openai.com/v1/chat/completions"
MODEL = "gpt-4o-mini"
MAX_TEXT_CHARS = 12_000

SYSTEM_PROMPT = """당신은 한국 수출 실무 담당자를 돕는 서류 검토자입니다.
사용자가 올린 증빙 서류의 텍스트와, 그 서류가 딸린 수출 건의 정보를 받습니다.

할 일은 두 가지입니다.
1. 서류가 어떤 종류인지 읽어 냅니다.
2. 서류에 적힌 값이 수출 건의 값과 어긋나지 않는지 대조합니다.

지켜야 할 것:
- 서류에 없는 내용을 지어내지 않습니다. 안 보이면 "서류에서 찾지 못함"이라고 씁니다.
- "이 서류는 법적으로 유효하다"고 단정하지 않습니다. 최종 판단은 세관과 수입국이 합니다.
- 유효기간이 지났거나 곧 지나면 반드시 짚습니다.
- 모든 설명은 한국어로, 무역을 처음 하는 사람도 알아들을 수 있게 씁니다.

아래 JSON 형식으로만 답합니다.
{
  "document_type": "읽어 낸 서류 종류",
  "status": "ok" | "check" | "mismatch",
  "summary": "한두 문장 요약",
  "findings": [
    {"label": "대조한 항목", "verdict": "match" | "missing" | "differs",
     "detail": "무엇이 어떻게 다른지, 어떻게 해야 하는지"}
  ]
}
status는 어긋난 것이 없으면 ok, 확인이 더 필요하면 check,
이 건의 화물과 다른 서류로 보이면 mismatch 입니다."""


def available() -> bool:
    return bool(get_config("AI_API_KEY", ""))


def structured_chat(messages: list[dict], schema: dict, *, name: str,
                    max_tokens: int = 1800, model: str = "", timeout: float = 25) -> dict:
    """Schema-constrained output for product interpretation, with explicit failure.

    messages의 content에는 그림도 넣을 수 있습니다({"type": "image_url", ...}).
    서류 사진을 읽을 때는 시간이 더 걸려 timeout을 늘려 부릅니다.
    """
    key = get_config("AI_API_KEY", "")
    if not key:
        return fail("API_AUTH_FAILED", "api", "OpenAI 키가 없어 일반 검색을 사용합니다.")
    result = request_text("POST", OPENAI_URL, timeout=timeout,
                          headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                          json={"model": model or get_config("AI_HS_MODEL", MODEL), "temperature": 0,
                                "max_tokens": max_tokens, "messages": messages,
                                "response_format": {"type": "json_schema", "json_schema": {
                                    "name": name, "strict": True, "schema": schema}}})
    if not result["success"]:
        return result
    try:
        choice = json.loads(result["data"])["choices"][0]
        message = choice["message"]
        if message.get("refusal") or choice.get("finish_reason") != "stop":
            return fail("API_INVALID_RESPONSE", "api", "AI 분석을 완료하지 못해 일반 검색을 사용합니다.")
        payload = json.loads(message["content"])
        if not isinstance(payload, dict):
            raise ValueError("Expected object")
        return ok(payload, "api")
    except (ValueError, KeyError, IndexError, TypeError):
        return fail("API_INVALID_RESPONSE", "api", "AI 응답을 해석하지 못해 일반 검색을 사용합니다.")


def chat(messages: list[dict], *, max_tokens: int = 700) -> dict:
    """대화 한 번. 답은 글자 그대로 돌려줍니다. (고객상담 창에서 씁니다)"""

    key = get_config("AI_API_KEY", "")
    if not key:
        return fail("API_AUTH_FAILED", "api",
                    "AI 상담 키(AI_API_KEY)가 없습니다. .env에 키를 넣으면 바로 동작합니다.")

    result = request_text("POST", OPENAI_URL, timeout=60,
                          headers={"Authorization": f"Bearer {key}",
                                   "Content-Type": "application/json"},
                          json={"model": MODEL, "temperature": 0.2,
                                "max_tokens": max_tokens, "messages": messages})
    if not result["success"]:
        return result
    try:
        body = json.loads(result["data"])
        answer = body["choices"][0]["message"]["content"].strip()
    except (ValueError, KeyError, IndexError):
        return fail("API_INVALID_RESPONSE", "api", "AI 응답을 해석하지 못했습니다.")
    if not answer:
        return fail("API_NO_DATA", "api", "답변이 비어 있습니다. 다시 물어봐 주세요.")
    return ok(answer, "api")


def review_document(document_text: str, context: dict) -> dict:
    """서류 텍스트와 수출 건 정보를 대조합니다."""

    key = get_config("AI_API_KEY", "")
    if not key:
        return fail("API_AUTH_FAILED", "api",
                    "AI 분석 키(AI_API_KEY)가 없습니다. .env에 키를 넣으면 업로드한 "
                    "서류를 자동으로 대조해 드립니다.")

    text = (document_text or "").strip()
    if not text:
        return fail("VALIDATION_ERROR", "api",
                    "서류에서 글자를 읽지 못했습니다. 스캔 이미지만 들어 있는 PDF이거나 "
                    "지원하지 않는 형식일 수 있습니다.")

    payload = {
        "model": MODEL,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps({
                "수출_건": context,
                "서류_본문": text[:MAX_TEXT_CHARS],
            }, ensure_ascii=False)},
        ],
    }
    result = request_text("POST", OPENAI_URL, timeout=60,
                          headers={"Authorization": f"Bearer {key}",
                                   "Content-Type": "application/json"},
                          json=payload)
    if not result["success"]:
        return result
    try:
        body = json.loads(result["data"])
        content = body["choices"][0]["message"]["content"]
        parsed = json.loads(content)
    except (ValueError, KeyError, IndexError):
        return fail("API_INVALID_RESPONSE", "api", "AI 응답을 해석하지 못했습니다.")

    status = parsed.get("status")
    if status not in ("ok", "check", "mismatch"):
        status = "check"
    findings = [
        {
            "label": str(row.get("label", ""))[:120],
            "verdict": row.get("verdict") if row.get("verdict") in ("match", "missing", "differs") else "missing",
            "detail": str(row.get("detail", ""))[:600],
        }
        for row in (parsed.get("findings") or [])[:20]
        if isinstance(row, dict)
    ]
    return ok({
        "document_type": str(parsed.get("document_type", ""))[:120],
        "status": status,
        "summary": str(parsed.get("summary", ""))[:600],
        "findings": findings,
    }, "api")
