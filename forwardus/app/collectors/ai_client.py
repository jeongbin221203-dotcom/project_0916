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
OPENAI_EMBED_URL = "https://api.openai.com/v1/embeddings"
MODEL = "gpt-4o-mini"
# FAQ 검색에 쓰는 임베딩. 말이 달라도 뜻이 비슷하면 찾으라고 씁니다.
# ("배에 실은 다음부터 누가 책임지나요" ↔ "FOB 위험 이전 시점")
EMBED_MODEL = "text-embedding-3-small"
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


def embed(texts: list[str], *, timeout: float = 20) -> dict:
    """글 여러 개를 벡터로. 실패하면 부르는 쪽이 낱말 검색으로 돌아갑니다."""

    key = get_config("AI_API_KEY", "")
    if not key:
        return fail("API_AUTH_FAILED", "api", "AI 키(AI_API_KEY)가 없습니다.")
    if not texts:
        return ok([], "api")
    result = request_text("POST", OPENAI_EMBED_URL, timeout=timeout,
                          headers={"Authorization": f"Bearer {key}",
                                   "Content-Type": "application/json"},
                          json={"model": EMBED_MODEL, "input": texts})
    if not result["success"]:
        return result
    try:
        rows = json.loads(result["data"])["data"]
        return ok([row["embedding"] for row in sorted(rows, key=lambda row: row["index"])], "api")
    except (ValueError, KeyError, TypeError):
        return fail("API_INVALID_RESPONSE", "api", "임베딩 응답을 해석하지 못했습니다.")


def structured_chat(messages: list[dict], schema: dict, *, name: str,
                    max_tokens: int = 1800, model: str | None = None,
                    timeout: float = 25) -> dict:
    """Schema-constrained output for product interpretation, with explicit failure.

    messages의 content에 이미지 조각({"type": "image_url", ...})을 넣으면
    Vision으로 읽습니다. 그림을 읽는 호출은 느려서 timeout을 늘려 부릅니다.
    model을 비우면(None 또는 "") AI_HS_MODEL을 씁니다.
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


# 도구를 부르고 결과를 받아 다시 묻는 왕복의 최대 횟수. 비교 질문은 나라 여럿을 부르므로
# 한 번에 여러 도구를 부르게 두고(parallel tool calls), 왕복은 몇 번으로 막습니다.
MAX_TOOL_ROUNDS = 3
# 도구 결과 하나를 AI에게 넘길 때의 최대 글자 수. 넘으면 뒤를 자릅니다.
MAX_TOOL_OUTPUT_CHARS = 12_000


def chat(messages: list[dict], *, max_tokens: int = 700, tools: list[dict] | None = None,
         run_tool=None, force_tool: bool = False) -> dict:
    """대화 한 번. 답은 글자 그대로 돌려줍니다. (고객상담 창에서 씁니다)

    tools(OpenAI function 정의)와 run_tool(name, arguments) -> dict 를 주면 Function Calling을
    씁니다. AI가 도구를 부르면 우리 코드가 실제 API를 불러 결과를 돌려주고, AI는 그 결과로 답을
    씁니다. 어떤 도구를 불렀는지는 결과의 "tools_used"에 남깁니다. (화면이 근거를 표시합니다)
    force_tool이면 첫 왕복에서 도구를 반드시 부르게 합니다. (수치를 물었는데 기억으로 답하는 것을 막습니다)
    """

    key = get_config("AI_API_KEY", "")
    if not key:
        return fail("API_AUTH_FAILED", "api",
                    "AI 상담 키(AI_API_KEY)가 없습니다. .env에 키를 넣으면 바로 동작합니다.")

    messages = list(messages)
    used: list[dict] = []
    for round_no in range(MAX_TOOL_ROUNDS + 1):
        payload = {"model": MODEL, "temperature": 0.2, "max_tokens": max_tokens,
                   "messages": messages}
        # 마지막 왕복에서는 도구를 빼서 반드시 글로 답하게 합니다.
        if tools and run_tool and round_no < MAX_TOOL_ROUNDS:
            payload["tools"] = tools
            payload["tool_choice"] = "required" if force_tool and round_no == 0 else "auto"
        result = request_text("POST", OPENAI_URL, timeout=60,
                              headers={"Authorization": f"Bearer {key}",
                                       "Content-Type": "application/json"},
                              json=payload)
        if not result["success"]:
            return result
        try:
            message = json.loads(result["data"])["choices"][0]["message"]
        except (ValueError, KeyError, IndexError, TypeError):
            return fail("API_INVALID_RESPONSE", "api", "AI 응답을 해석하지 못했습니다.")

        calls = message.get("tool_calls") or []
        if calls and run_tool:
            messages.append({"role": "assistant", "content": message.get("content"),
                             "tool_calls": calls})
            for call in calls:
                name = (call.get("function") or {}).get("name", "")
                try:
                    arguments = json.loads((call.get("function") or {}).get("arguments") or "{}")
                except ValueError:
                    arguments = {}
                output = run_tool(name, arguments if isinstance(arguments, dict) else {})
                used.append({"name": name, "arguments": arguments,
                             "success": bool(output.get("success")),
                             "source": output.get("source", ""), "output": output})
                messages.append({"role": "tool", "tool_call_id": call.get("id", ""),
                                 "content": json.dumps(output, ensure_ascii=False)[:MAX_TOOL_OUTPUT_CHARS]})
            continue

        answer = (message.get("content") or "").strip()
        if not answer:
            return fail("API_NO_DATA", "api", "답변이 비어 있습니다. 다시 물어봐 주세요.")
        response = ok(answer, "api")
        if used:
            response["tools_used"] = used
        return response
    return fail("API_NO_DATA", "api", "답변을 마치지 못했습니다. 다시 물어봐 주세요.")


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
