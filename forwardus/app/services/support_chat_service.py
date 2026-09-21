"""고객상담 — 무역 실무를 물어보면 답해 주는 창구.

화면 어디에서나 부를 수 있습니다. Shipment에 딸린 AI Assistant와 달리 특정
건에 묶이지 않고, 수출 절차 전반을 묻는 자리입니다.

지켜야 할 것이 하나 있습니다. 숫자와 규정은 지어내지 않습니다. 우리 화면이
이미 계산해 둔 값이 있으면 그 값을 쓰고, 없으면 "어디서 확인하면 된다"를
알려 줍니다. 세율·요건·운임을 짐작해서 말하면 사람이 그대로 믿고 손해를
봅니다.
"""

from __future__ import annotations

from app.collectors import ai_client
from app.processors import export_requirements
from app.services import ServiceError

MAX_QUESTION = 2_000
MAX_HISTORY = 8

SYSTEM_PROMPT = """당신은 한국 중소 수출기업을 돕는 FORWARDUS의 상담원입니다.
수출을 처음 해 보는 사람이 묻습니다. 무역 용어를 모른다고 전제하세요.

말하는 법
- 한국어로, 짧은 문장으로 씁니다. 한 문장에 한 가지만 담습니다.
- 영문 약어(FOB, B/L, HS, C/O 같은 것)는 처음 쓸 때 우리말로 풀어 줍니다.
- 결론부터 말하고, 그다음에 이유를 답니다.
- 답을 모르면 모른다고 합니다. 그리고 어디서 확인하면 되는지 알려 줍니다.

절대 하지 말 것
- 관세율·협정세율·운임·환율을 기억에서 꺼내 숫자로 말하지 마세요.
  이 값들은 품목과 시점마다 달라 틀리면 사람이 손해를 봅니다.
  대신 "운송 계획 화면에서 HS부호를 넣으면 도착국 세율을 조회해 드립니다"처럼
  우리 기능을 안내하세요.
- "이 물건은 수출 가능합니다" 같은 단정을 하지 마세요.
  최종 판단은 세관과 수입국이 합니다.
- 법령 조문 번호를 확실하지 않은 채로 인용하지 마세요.

이 서비스가 할 수 있는 일 (물어보면 안내하세요)
- 운송 계획: 출발·도착지와 날짜를 넣으면 스케줄·운임 추정·물류비 견적
- 화물 계산: 치수와 수량으로 CBM·중량·컨테이너 수·항공 운임중량
- HS부호 찾기: 한글 품명으로 관세청에서 조회
- 도착국 관세: 품목별로 상대국이 매기는 세율 조회
- 서류: 상업송장·포장명세서 자동 작성, 서류 간 대조 검증
- 수출요건: HS부호로 식품·화장품·전략물자 등 확인할 것 안내, 증빙 서류 AI 대조
- 원산지증명서: 협정별 발급 방식과 신청 창구 안내, 발급받은 것 등록
- 관세사 전달용 수출신고 자료 자동 정리

답변은 5문장을 넘기지 마세요. 더 필요하면 되물어 주세요."""

# Incoterms는 우리가 이미 정확한 정의를 들고 있습니다. 기억에 맡기면 틀립니다.
# (실제로 FOB를 "자유 온도 선적"이라고 답한 적이 있습니다.)
def _incoterms_reference() -> str:
    from app.processors.cost_calculator import INCOTERMS_INFO

    lines = ["아래는 Incoterms 2020의 확정된 정의입니다. 이 표현을 그대로 쓰세요.",
             "여기 없는 뜻을 지어내지 마세요."]
    for row in INCOTERMS_INFO:
        lines.append(
            f"- {row['code']} ({row['name']}, {row['label']}): "
            f"위험 이전 {row['risk']} / 판매자 부담 {row['seller_cost']}. {row['detail']}")
    return "\n".join(lines)


def available() -> bool:
    return ai_client.available()


# 원산지증명서를 어디서 받는지 묻는 말들.
ORIGIN_WORDS = ("원산지증명서", "원산지 증명서", "c/o", "certificate of origin", "코오")
ORIGIN_ASKING = ("어디서", "어디에", "어떻게", "발급", "신청", "받", "떼", "구하")


def _asks_about_origin(text: str) -> bool:
    lowered = text.lower()
    return (any(word in lowered for word in ORIGIN_WORDS)
            and any(word in lowered for word in ORIGIN_ASKING))


def origin_answer() -> str:
    """원산지증명서 신청 창구를 그 자리에서 알려 줍니다.

    "어느 화면으로 가세요"라고 미루지 않습니다. 물어본 자리에서 답이
    나와야 합니다. 주소는 우리가 들고 있는 값을 그대로 쓰고, AI에게
    받아 적게 하지 않습니다. AI가 기억으로 주소를 만들면 없는 주소가
    나오고, 사람은 그걸 믿고 헤맵니다.
    """

    from app.processors import fta_guide

    lines = ["원산지증명서는 **발급 기관이 따로 있습니다.** 저희가 대신 만들어 드릴 수 "
             "없고, 협정마다 서식과 발급처가 다릅니다.", "",
             "**신청 창구**", ""]
    for row in fta_guide.all_apply_links():
        lines.append(f"- [{row['label']}]({row['url']})")
        lines.append(f"  {row['note']}")
    non = fta_guide.NON_PREFERENTIAL
    lines += ["", f"**{non['label']}**", "",
              non["about"], "", f"발급: {non['issuer']}", "",
              "어느 협정으로 받아야 하는지는 **HS부호와 도착국**에 따라 갈립니다. "
              "품목과 보내실 나라를 알려 주시면 이 건에 쓸 수 있는 협정을 찾아 드립니다.", "",
              "발급받으신 PDF는 서류 화면에 올리시면 이 건의 품명·HS부호·수출자와 "
              "맞는지 대조해 드립니다."]
    return "\n".join(lines)


def ask(question: str, history: list | None = None) -> dict:
    """질문 하나에 답합니다. history는 [{role, content}] 형태입니다."""

    text = (question or "").strip()
    if not text:
        raise ServiceError("무엇이 궁금한지 적어주세요.", "VALIDATION_ERROR")
    if len(text) > MAX_QUESTION:
        raise ServiceError(f"질문은 {MAX_QUESTION:,}자까지 보낼 수 있습니다.", "VALIDATION_ERROR")

    # 주소가 걸린 질문은 우리가 직접 답합니다. AI에게 맡기면 없는 주소를
    # 지어낼 수 있고, 기관 주소는 틀리면 사람이 그대로 헤맵니다.
    if _asks_about_origin(text):
        return {"success": True, "source": "calculated",
                "data": {"answer": origin_answer()}}

    messages = [{"role": "system", "content": SYSTEM_PROMPT},
                {"role": "system", "content": _incoterms_reference()}]
    for turn in (history or [])[-MAX_HISTORY:]:
        role = turn.get("role")
        content = str(turn.get("content") or "").strip()[:MAX_QUESTION]
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": text})

    result = ai_client.chat(messages)
    if not result["success"]:
        return {"success": False, "message": result["message"], "source": result["source"]}
    return {"success": True, "source": "api", "data": {"answer": result["data"]}}


# 처음 열었을 때 보여 주는 예시 질문. 무엇을 물어도 되는지 알려 줍니다.
SUGGESTIONS = [
    "수출할 때 꼭 준비해야 하는 서류가 뭔가요?",
    "FOB랑 CIF가 어떻게 다른가요?",
    "HS부호는 어떻게 찾나요?",
    "원산지증명서는 어디서 받나요?",
]

GREETING = ("안녕하세요. 수출 절차에서 막히는 것이 있으면 물어보세요.\n"
            "관세율이나 운임 같은 숫자는 제가 짐작하지 않고, 조회해 드릴 수 있는 "
            "화면으로 안내합니다.")


def intro() -> dict:
    """상담창을 열었을 때 보여 줄 것."""

    return {
        "greeting": GREETING,
        "suggestions": list(SUGGESTIONS),
        "available": available(),
        "offline_note": ("AI 상담 키(AI_API_KEY)가 없어 지금은 답변할 수 없습니다. "
                         ".env에 키를 넣으면 바로 동작합니다."),
        "lookup_links": [
            {"label": link["label"], "url": link["url"]}
            for link in export_requirements.LOOKUP_LINKS.values()
        ][:3],
    }
