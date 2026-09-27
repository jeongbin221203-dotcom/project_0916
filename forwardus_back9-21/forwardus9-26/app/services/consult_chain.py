"""상담 처리 경로. LangChain(langchain-core)으로 엮습니다.

왜 LangChain인가 — 그리고 어디까지만 쓰는가
  이 프로젝트는 원래 httpx로 OpenAI를 직접 부릅니다. 그 호출을 통째로 바꾸면 이미 도는
  코드를 위험하게 건드리게 되고, langchain-openai를 붙이면 openai SDK까지 따라옵니다.
  그래서 langchain-core의 네 가지만 씁니다.
    BaseRetriever    FAQ 검색기를 LangChain 검색기로 노출 (faq_index 재사용)
    StructuredTool   공식 조회 함수를 입출력 스키마가 있는 도구로 노출 (consult_tools)
    Runnable         아래 다섯 단계를 하나의 체인으로 엮음
    콜백             단계별 시간을 체인 바깥이 아니라 체인 실행에서 받아 적음
  답을 만드는 LLM 호출은 기존 ai_client를 체인의 마지막 단계 안에서 부릅니다. 그래서
  LangChain 경로와 기존 경로가 두 번 부르는 일이 없습니다.

실제 요청이 지나는 체인 (CHAIN, RunnableSequence)
    analyze_question   의도·조건 읽기            consult_intent (AI 호출 없음)
  → search_faq         FAQ 검색                  FaqRetriever(BaseRetriever)
  → decide_route       다섯 경로 중 하나로 분기   decide()
  → official_lookup    공식 조회                 StructuredTool
  → write_answer       답 쓰기                   ai_client (필요한 경로에서만)
  `support_chat_service.ask()`는 이 체인을 `run()`으로 한 번 부릅니다. 예전에는 체인
  객체만 만들어 두고 실제로는 같은 일을 손으로 다시 했습니다(체인 호출 0회). 지금은
  단계 시간이 LangChain 콜백에서 나오므로, 값이 찍혔다는 것 자체가 체인이 돌았다는
  증거입니다. FAQ 검색도 여기 한 번만 일어납니다(예전에는 두 번 돌았습니다).

경로 (decide → run)
  faq_direct        전문가 승인(approved) FAQ + 조건 일치 + 최신 조회 불필요 → AI 없이 반환
  faq_context       FAQ를 근거로 AI가 답함 (미승인 자료는 '참고'로만 넘김)
  external_lookup   공식 도구 조회 후 그 근거로 AI가 답함
  clarification     조건이 모자라면 되물음 (AI 없이, 무엇이 필요한지 우리가 압니다)
  general_guidance  공식 근거를 못 얻었을 때 일반 안내 + 확인처 (규정 단정 금지)
"""

from __future__ import annotations

import re
import threading
import time

from langchain_core.callbacks import BaseCallbackHandler, CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from langchain_core.runnables import RunnableLambda
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from app.services import consult_intent, consult_tools, faq_index

# 도구는 한 질문에 이만큼까지만 부릅니다. 같은 실패를 되풀이하지 않게 결과를 기억합니다.
MAX_TOOL_CALLS = 3
# 검색해 올 FAQ 수. 근거로 붙이는 건 앞의 3건이고, 나머지는 경로 판단에 씁니다.
SEARCH_K = 5
# 이 경로들만 AI에게 답을 맡깁니다. 나머지(승인 FAQ 그대로·되묻기)는 AI를 부르지 않습니다.
NEEDS_ANSWER = ("faq_context", "external_lookup", "general_guidance")
TOOL_DEADLINE_SECONDS = 30
# 시점에 민감한 말. 이런 말이 있으면 FAQ가 있어도 공식 조회로 넘깁니다.
FRESHNESS_WORDS = ("올해", "내년", "작년", "최근", "요즘", "지금", "현재", "바뀌", "개정", "변경",
                   "신설", "폐지", "시행", "언제부터", "적용일", "최신", "이번", "2025", "2026", "2027")
# 규정·세율처럼 "지금 무엇이 맞는지" 확인해야 하는 말
REGULATION_WORDS = ("요건", "규제", "허가", "승인", "인증", "세율", "관세율", "관세", "환급",
                    "금지", "제한", "표시", "성분", "등록", "신고대상", "세관장확인", "전략물자")
HS6 = re.compile(r"\b(\d{4})[.\-]?(\d{2})\b")
HSK10 = re.compile(r"\b(\d{10})\b")
COUNTRY_NAMES = {"미국": "US", "usa": "US", "미국향": "US", "일본": "JP", "중국": "CN",
                 "베트남": "VN", "인도네시아": "ID", "인도": "IN", "독일": "EU", "유럽": "EU",
                 "태국": "TH", "호주": "AU", "멕시코": "MX", "uae": "AE", "러시아": "RU"}


# --- 1. FAQ 검색기를 LangChain 검색기로 ---------------------------------------------

def search_for(question: str, history: list | None = None, k: int = 5) -> tuple:
    """검색에 쓸 말을 정해 찾습니다.

    **원문 그대로 찾습니다.** 핵심 질문만 뽑아 찾는 방법과 둘을 합치는 방법을 튜닝
    데이터(140문항)로 견줘 봤더니 원문이 가장 좋았습니다(2026-09-24):
        긴 자연어 질문 Recall@1  원문 0.929 · 핵심만 0.643 · 합치기 0.821
        오탈자          원문 0.900 · 핵심만 0.900 · 합치기 0.900
    상황 설명이 붙어도 낱말이 많아질 뿐 점수는 떨어지지 않았습니다. 그래서 줄이지 않습니다.
    (핵심·조건 나누기는 의도 판단과 되묻기에만 씁니다 — consult_intent)

    다만 "아니라 베트남으로 바뀌었어요" 같은 짧은 후속·정정 질문은 그 문장만으로는
    무슨 주제인지 알 수 없습니다. 그때만 앞에서 사람이 한 말을 붙여 찾습니다.
    """

    text = str(question or "").strip()
    if _needs_history(text) and history:
        earlier = [str(turn.get("content") or "") for turn in history[-4:]
                   if turn.get("role") == "user"]
        if earlier:
            return faq_index.search(f"{earlier[-1]} {text}", k)
    return faq_index.search(text, k)


def _needs_history(question: str) -> bool:
    """이 문장만으로 주제를 알 수 없는 질문인가. (정정·짧은 후속)"""

    text = str(question or "")
    short = len(text.replace(" ", "")) < 25
    correction = bool(consult_intent.CORRECTION.search(text))
    refers_back = bool(re.search(r"(아까|방금|위에서|그럼|그러면|이 경우|말씀하신)", text))
    return (correction or refers_back) and short or (refers_back and correction)


class FaqRetriever(BaseRetriever):
    """faq_index를 그대로 쓰는 LangChain 검색기. (색인을 두 벌 만들지 않습니다)

    상담 한 건마다 새로 만듭니다. 앞 대화(history)를 들고 있어야 "아니라 베트남으로"
    같은 정정 질문을 제대로 찾는데, 모듈에 하나만 두면 여러 요청이 그 값을 덮어씁니다.
    """

    k: int = SEARCH_K
    history: list | None = None

    def _get_relevant_documents(self, query: str, *,
                                run_manager: CallbackManagerForRetrieverRun | None = None
                                ) -> list[Document]:
        hits = search_for(query, self.history, self.k)
        return [Document(page_content=faq_index.answer_text(faq),
                         metadata={"faq_id": faq["id"], "category": faq.get("category", ""),
                                   "score": score, "coverage": coverage, "similarity": similarity,
                                   "review_status": faq.get("review_status", ""),
                                   "freshness": faq.get("freshness", ""),
                                   "sources": faq.get("sources", []),
                                   "applicability": faq.get("applicability", {}),
                                   "faq": faq})
                for faq, score, coverage, similarity in hits]


def hits_of(documents: list) -> list[tuple]:
    """검색기가 돌려준 Document를 faq_index가 쓰는 (faq, 점수, 적중률, 유사도)로 되돌립니다.

    이렇게 해야 검색을 한 번만 하고도 경로 판단(faq_index.decide_with_hits)이 예전과
    똑같은 입력을 받습니다. 형식만 LangChain으로 바꾼 것이지 점수는 그대로입니다.
    """

    return [(document.metadata["faq"], document.metadata["score"],
             document.metadata["coverage"], document.metadata["similarity"])
            for document in documents if document.metadata.get("faq")]


# --- 2. 공식 조회 함수를 LangChain 도구로 --------------------------------------------

class KoreaRequirementInput(BaseModel):
    hs_code: str = Field(description="한국 HSK 10자리 숫자. 6자리만 알면 빈 값으로 두세요.")
    direction: str = Field(default="1", description='"1" 수출(기본) · "2" 수입. 한국 기준입니다.')


class RefundInput(BaseModel):
    hs_code: str = Field(description="한국 HSK 10자리 숫자")


class DestinationTariffInput(BaseModel):
    country_code: str = Field(description="수입국 2자리 코드 (US, JP 등)")
    hs_code: str = Field(description="HS 6자리 숫자")


class RulingsInput(BaseModel):
    query: str = Field(description="품명(영문이 더 정확합니다). 예: cosmetic cream")
    hs_code: str = Field(default="", description="HS 6자리 숫자(있으면)")


class FdaInput(BaseModel):
    query: str = Field(description="품명(영문). 예: kimchi, catheter")
    kind: str = Field(default="food", description='"food" 식품 · "device" 의료기기')


class StatisticsInput(BaseModel):
    hs_code: str = Field(default="", description="HS 코드")
    country: str = Field(default="", description="상대국 이름 또는 코드")
    year: str = Field(default="", description="조회 연도(비우면 최근)")


TOOLS = [
    StructuredTool.from_function(
        func=consult_tools.korea_export_requirements, name="korea_export_requirements",
        description="한국에서 보낼 때 세관장확인대상인지(관세법 제226조: 어떤 법령·요건승인기관·요건확인서류·적용시작일) 관세청 공공데이터로 조회합니다. HSK 10자리 필요. direction은 1 수출·2 수입.",
        args_schema=KoreaRequirementInput),
    StructuredTool.from_function(
        func=consult_tools.korea_refund_rate, name="korea_refund_rate",
        description="수출 후 받을 수 있는 간이정액환급액을 관세청 공고표에서 조회합니다. HSK 10자리 필요.",
        args_schema=RefundInput),
    StructuredTool.from_function(
        func=consult_tools.destination_tariff, name="destination_tariff",
        description="수입국 관세율표에서 해당 세번 줄을 찾습니다. 지금은 미국(US)·일본(JP)만 연결되어 있습니다.",
        args_schema=DestinationTariffInput),
    StructuredTool.from_function(
        func=consult_tools.us_classification_rulings, name="us_classification_rulings",
        description="미국 세관(CBP)이 비슷한 물건을 어떻게 분류했는지 과거 판례를 찾습니다. 판정이 아니라 참고 사례입니다.",
        args_schema=RulingsInput),
    StructuredTool.from_function(
        func=consult_tools.us_fda_records, name="us_fda_records",
        description="미국 FDA 회수·집행 기록(openFDA)을 찾습니다. 규정 조문이 아니고 규제 대상 여부 판정도 아닙니다.",
        args_schema=FdaInput),
    StructuredTool.from_function(
        func=consult_tools.trade_statistics, name="trade_statistics",
        description="관세청 품목별 수출실적 통계. 규정이 아니라 시장 자료입니다.",
        args_schema=StatisticsInput),
]
TOOLS_BY_NAME = {tool.name: tool for tool in TOOLS}


# --- 3. 질문에서 조건 뽑기 ----------------------------------------------------------

def read_conditions(question: str, history: list | None = None) -> dict:
    """질문과 앞 대화에서 나라·HS·품목을 읽습니다. 없는 것을 지어내지 않습니다.

    앞 대화까지 보는 이유: 사용자가 이미 말한 것을 다시 묻지 않기 위해서입니다.
    """

    text = str(question or "")
    earlier = " ".join(str(turn.get("content") or "") for turn in (history or [])[-6:]
                       if turn.get("role") == "user")
    joined = f"{earlier} {text}"
    lowered = joined.lower()

    hsk = HSK10.search(joined)
    hs6 = HS6.search(joined)
    countries = {code for name, code in COUNTRY_NAMES.items() if name in lowered}
    asked = faq_index.question_conditions(text)
    return {"hs10": hsk.group(1) if hsk else "",
            "hs6": (hs6.group(1) + hs6.group(2)) if hs6 else "",
            "countries": sorted(countries | asked["countries"]),
            "items": sorted(asked["items"]),
            "terms": sorted(asked["terms"]),
            "payments": sorted(asked["payments"]),
            "from_history": bool(earlier.strip())}


def needs_fresh_lookup(question: str) -> bool:
    """지금 무엇이 맞는지 확인해야 하는 질문인가. FAQ·캐시가 이걸 건너뛰지 못하게 합니다."""

    lowered = str(question or "").lower()
    regulation = any(word in lowered for word in REGULATION_WORDS)
    fresh = any(word in lowered for word in FRESHNESS_WORDS)
    return regulation and (fresh or bool(HS6.search(lowered)) or bool(HSK10.search(lowered)))


# --- 4. 경로 판단 -------------------------------------------------------------------

def conditions_for(question: str, history: list | None = None, parts: dict | None = None) -> dict:
    """답을 바꾸는 조건 한 벌. 경로 판단과 캐시 열쇠가 **같은 값**을 써야 합니다.

    예전에는 두 곳에서 따로 계산했고, 한쪽만 "사용자가 고친 값이 앞 조건을 덮는다"를
    처리해서 "아니라 베트남으로" 뒤에도 캐시 열쇠에 미국이 남았습니다. 그래서 하나로 모읍니다.
    """

    parts = parts or consult_intent.split_question(question, history)
    conditions = dict(parts["conditions"])
    conditions["items"] = conditions.get("item_words") or []
    hs = conditions.get("hs") or ""
    conditions["hs6"] = hs[:6] if len(hs) >= 6 else ""
    conditions["hs10"] = conditions.get("hs10") or (hs if len(hs) == 10 else "")
    return conditions


def decide(question: str, history: list | None = None, *,
           parts: dict | None = None, hits: list | None = None) -> dict:
    """어느 길로 갈지 정합니다. (AI를 부르기 전에, 우리 규칙으로)

    parts·hits는 체인의 앞 단계가 이미 구한 값입니다. 주면 그대로 쓰고, 안 주면
    여기서 구합니다. 덕분에 체인에서는 의도 읽기와 검색이 각각 한 번씩만 돕니다.

    순서
      1. 의도와 조건을 읽습니다 (consult_intent · AI 호출 없음)
      2. 답이 달라지는 조건이 비었으면 되묻습니다 (clarification)
      3. 지금 시점 확인이 필요하면 공식 조회 (external_lookup)
      4. 아니면 FAQ (승인분은 faq_direct · 나머지는 faq_context)
      5. 어느 것도 아니면 일반 안내 (general_guidance)
    모든 갈림길의 이유를 reasons에 남깁니다. 로그에서 왜 그 길로 갔는지 읽을 수 있어야 합니다.
    """

    parts = parts or consult_intent.split_question(question, history)
    conditions = conditions_for(question, history, parts)
    # 조건은 consult_intent 것을 씁니다. 그쪽만 "사용자가 고친 값이 앞 조건을 덮는다"를
    # 처리합니다. 예전 read_conditions를 뒤에 덧씌우면 "미국"이라고 했던 것이 되살아나
    # "아니라 베트남으로 바뀌었어요" 뒤에도 미국이 남습니다. (2026-09-25 실제로 그랬습니다)

    intent = parts["intent"]
    verdict = faq_index.decide_with_hits(
        question, search_for(question, history, SEARCH_K) if hits is None else hits)
    fresh = needs_fresh_lookup(question)
    faq = verdict.get("faq")
    approved = bool(faq) and (faq.get("review") or {}).get("review_status") == "approved"

    plan = {"route": "general_guidance", "conditions": conditions, "faq": faq,
            "candidates": verdict.get("candidates", ()), "needs_fresh": fresh,
            "faq_route": verdict["route"], "reasons": list(verdict.get("reasons", [])),
            "tool_calls": [], "approved": approved, "intent": intent,
            "core_question": parts["core"], "missing": []}

    # 이미 공식 조회를 돌릴 수 있으면 되묻지 않습니다. 있는 것을 또 묻지 않기 위해서입니다.
    ready_tools = _plan_tools(question, conditions)
    if ready_tools:
        plan["tool_calls"] = ready_tools
        plan["route"] = "external_lookup"
        plan["reasons"].append("조건이 갖춰져 공식 조회로 바로 갑니다")
        return plan

    # 답이 달라지는 조건이 비었으면 되묻습니다. 용어 뜻 질문은 묻지 않습니다.
    asks = consult_intent.missing_slots(intent, conditions, question)
    if asks:
        plan["route"] = "clarification"
        plan["missing"] = asks
        plan["reasons"].append(f"의도 '{intent}'에 필요한 조건이 비어 되물음")
        return plan

    if fresh:
        # 규정·세율을 지금 시점으로 물었습니다. (조회할 도구가 있으면 위에서 이미 갔습니다)
        # 한국 수출요건(세관장확인대상)은 HSK 10자리라야 조회됩니다. 그 질문일 때만 되묻습니다.
        korea_only = _asks_korea_requirement(question, conditions)
        if korea_only and not conditions["hs10"]:
            plan["route"] = "clarification"
            plan["missing"] = ["HSK 10자리 (관세청 세관장확인대상 조회는 10자리라야 됩니다. "
                               "6자리까지는 나라 공통이고 뒤 4자리가 한국 세번입니다)"]
            plan["reasons"].append("한국 수출요건 조회에 HSK 10자리가 필요")
            return plan
        # 수입국 규정·시행 예정처럼 우리가 확인해 줄 창구가 없는 질문입니다.
        # 조건을 더 받아도 조회가 안 되므로 되묻지 않고, 확인 기관을 안내합니다.
        plan["route"] = "general_guidance"
        plan["reasons"].append("최신 확인이 필요하지만 연결된 공식 조회 창구가 없어 "
                               "확인 기관을 안내합니다")
        return plan

    if verdict["route"] == "faq_direct":
        # 승인된 자료만 그대로 내보냅니다. 미승인이면 AI가 질문에 맞춰 다시 씁니다.
        plan["route"] = "faq_direct" if approved else "faq_context"
        if not approved:
            plan["reasons"].append("전문가 승인 전 자료라 그대로 반환하지 않습니다")
        return plan
    if verdict["route"] == "faq_context":
        plan["route"] = "faq_context"
        return plan

    plan["reasons"].append("맞는 FAQ가 없어 일반 안내")
    return plan


def _asks_korea_requirement(question: str, conditions: dict) -> bool:
    """한국에서 내보낼 때의 요건을 묻는가. (수입국 규정 질문과 가릅니다)

    "미국 화장품 인증" 처럼 상대국 규정을 물으면 우리 조회로는 답할 수 없습니다.
    그런 질문에 HSK 10자리를 되묻는 것은 사람을 헛돌게 만듭니다.
    """

    text = str(question or "")
    korea_words = ("세관장", "수출요건", "수출 요건", "수출신고", "관세청", "우리나라", "한국에서")
    foreign = bool(conditions.get("countries")) and not any(
        word in text for word in korea_words)
    asks_requirement = any(word in text for word in ("요건", "허가", "승인", "세관장", "규제"))
    return asks_requirement and not foreign


def _direction_of(question: str) -> str:
    """이 질문이 수출 이야기인지 수입 이야기인지. 세관장확인대상은 방향에 따라 답이 다릅니다.

    같은 HS라도 수출 요건과 수입 요건이 따로 있습니다(의약품은 수입만 걸립니다).
    방향을 잘못 넣으면 "걸리는 법령 없음"이라는 빈 결과가 나와 사람을 오해하게 만듭니다.
    """

    lowered = str(question or "").lower()
    imports = sum(lowered.count(word) for word in ("수입", "들여", "반입", "import"))
    exports = sum(lowered.count(word) for word in ("수출", "내보", "보내", "선적", "export"))
    return "2" if imports > exports else "1"


def _plan_tools(question: str, conditions: dict) -> list[dict]:
    """조건으로 실제 부를 수 있는 도구만 고릅니다. (없으면 빈 목록)"""

    calls: list[dict] = []
    lowered = question.lower()
    if conditions["hs10"]:
        if any(word in lowered for word in ("요건", "규제", "허가", "승인", "세관장", "인증", "금지", "제한")):
            calls.append({"tool": "korea_export_requirements",
                          "args": {"hs_code": conditions["hs10"],
                                   "direction": _direction_of(question)}})
        if "환급" in lowered:
            calls.append({"tool": "korea_refund_rate", "args": {"hs_code": conditions["hs10"]}})
    hs6 = conditions["hs6"] or conditions["hs10"][:6]
    for country in conditions["countries"]:
        if hs6 and country in ("US", "JP", "GB") and any(
                word in lowered for word in ("관세", "세율", "tariff", "hts")):
            calls.append({"tool": "destination_tariff",
                          "args": {"country_code": country, "hs_code": hs6}})
        # 미국 품목분류가 쟁점이면 CBP 판례를 참고로 함께 봅니다.
        if country == "US" and any(word in lowered for word in
                                   ("분류", "hs", "세번", "품목분류", "ruling", "판례")):
            item = " ".join(conditions.get("items") or []) or conditions.get("item_words") or []
            calls.append({"tool": "us_classification_rulings",
                          "args": {"query": (item if isinstance(item, str) else " ".join(item))
                                   or lowered[:40], "hs_code": hs6}})
        # 미국 식품·의료기기는 FDA 기록을 참고로 봅니다. (규정 조문이 아님을 도구가 밝힙니다)
        if country == "US" and any(word in lowered for word in
                                   ("식품", "음식", "의료기기", "fda", "리콜", "회수")):
            kind = "device" if "의료기기" in lowered else "food"
            words = conditions.get("items") or []
            calls.append({"tool": "us_fda_records",
                          "args": {"query": " ".join(words) or lowered[:30], "kind": kind}})
    return calls[:MAX_TOOL_CALLS]


def _missing_for_lookup(conditions: dict) -> list[str]:
    missing = []
    if not conditions["hs10"] and not conditions["hs6"]:
        missing.append("HS 코드(모르면 품명·재질·용도라도 알려 주세요)")
    if not conditions["countries"]:
        missing.append("어느 나라로 보내시나요")
    return missing


# --- 5. 실행 (LangChain Runnable) ----------------------------------------------------

def _run_tools(plan: dict, config: dict | None = None) -> list[dict]:
    """계획한 도구를 부릅니다. 같은 도구·같은 인자는 한 번만, 전체 제한시간 안에서만.

    config는 체인이 넘겨준 실행 설정입니다. 같이 넘겨야 도구 호출이 체인의 한 단계로
    기록됩니다. 안 넘기면 도구는 돌지만 체인 바깥에서 돈 것으로 남습니다.
    """

    started = time.perf_counter()
    seen: set = set()
    evidence: list[dict] = []
    for call in plan.get("tool_calls", [])[:MAX_TOOL_CALLS]:
        key = (call["tool"], tuple(sorted(call["args"].items())))
        if key in seen:
            continue
        seen.add(key)
        if time.perf_counter() - started > TOOL_DEADLINE_SECONDS:
            evidence.append(consult_tools.evidence(
                status=consult_tools.FAILED, question_scope=call["args"],
                note="조회 제한시간을 넘겨 멈췄습니다."))
            break
        tool = TOOLS_BY_NAME.get(call["tool"])
        if tool is None:
            continue
        try:
            evidence.append(tool.invoke(call["args"], config=config))
        except Exception as error:                   # noqa: BLE001 - 조회 실패도 결과의 하나입니다
            evidence.append(consult_tools.evidence(
                status=consult_tools.FAILED, question_scope=call["args"],
                note=f"{call['tool']} 조회 실패: {type(error).__name__}"))
    return evidence


def plan_question(plan: dict) -> str:
    faq = plan.get("faq") or {}
    return faq.get("question") or plan.get("question", "")


# --- 체인의 다섯 단계 ----------------------------------------------------------------
# 단계마다 payload(dict)를 받아 값을 하나 더 얹어 넘깁니다. 앞 단계가 구한 것을 뒷
# 단계가 다시 구하지 않게 하려고 이렇게 합니다.

def _analyze(payload: dict) -> dict:
    """무엇을 묻는지, 어떤 조건이 들어 있는지 읽습니다. AI를 부르지 않습니다."""

    question, history = payload["question"], payload.get("history")
    parts = consult_intent.split_question(question, history)
    return {**payload, "parts": parts,
            "conditions": conditions_for(question, history, parts)}


def _search(payload: dict, config: dict | None = None) -> dict:
    """FAQ를 찾습니다. LangChain 검색기(BaseRetriever)로 나갑니다.

    config를 함께 넘겨야 이 검색이 체인의 한 단계로 기록됩니다.
    """

    retriever = FaqRetriever(k=SEARCH_K, history=payload.get("history"))
    return {**payload, "documents": retriever.invoke(payload["question"], config=config)}


def _route(payload: dict) -> dict:
    """다섯 경로 중 하나를 고릅니다. 앞 단계가 찾아 둔 FAQ를 그대로 씁니다."""

    plan = decide(payload["question"], payload.get("history"),
                  parts=payload.get("parts"), hits=hits_of(payload["documents"]))
    plan["question"] = payload["question"]
    return {**payload, "plan": plan}


def _lookup(payload: dict, config: dict | None = None) -> dict:
    """공식 창구를 조회합니다. 부를 도구가 없으면 빈 목록입니다."""

    return {**payload, "evidence": _run_tools(payload["plan"], config)}


def _write(payload: dict) -> dict:
    """답을 씁니다. 답을 쓰는 함수는 부르는 쪽(support_chat_service)이 넘겨줍니다.

    여기서 ai_client를 직접 부르지 않는 이유: 답의 말투·길이·도구는 화면마다 다르고,
    그건 상담 서비스가 아는 일입니다. 체인은 '언제 쓰는가'만 정합니다.
    승인 FAQ를 그대로 내보내는 경로와 되묻는 경로에서는 AI를 부르지 않습니다.
    """

    writer = payload.get("write")
    if writer is None or payload["plan"]["route"] not in NEEDS_ANSWER:
        return {**payload, "answer": None}
    return {**payload, "answer": writer(payload)}


CHAIN = (RunnableLambda(_analyze, name="analyze_question")
         | RunnableLambda(_search, name="search_faq")
         | RunnableLambda(_route, name="decide_route")
         | RunnableLambda(_lookup, name="official_lookup")
         | RunnableLambda(_write, name="write_answer"))


# --- 단계별 시간 재기 (LangChain 콜백) -----------------------------------------------

class StageTimer(BaseCallbackHandler):
    """체인이 도는 동안 단계마다 걸린 시간을 받아 적습니다.

    왜 콜백으로 재는가
      체인 바깥에서 perf_counter()를 감으면 체인을 안 태워도 숫자가 나옵니다. 콜백은
      Runnable이 실제로 실행될 때만 불립니다. 그래서 여기 값이 있다는 것은 그 단계가
      정말 체인 안에서 돌았다는 뜻이고, counts()가 그 횟수를 그대로 보여 줍니다.

    RunnableParallel이나 도구가 다른 스레드에서 돌 수 있어 자물쇠를 씁니다.
    """

    STAGE_NAMES = {"analyze_question": "analyze_ms", "search_faq": "search_ms",
                   "decide_route": "route_ms", "official_lookup": "lookup_ms",
                   "write_answer": "llm_ms", "consult": "chain_ms"}

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._open: dict = {}
        self.spans: list[dict] = []

    # -- 기록 --------------------------------------------------------------------
    def _open_span(self, run_id, name: str, kind: str) -> None:
        with self._lock:
            self._open[run_id] = (name, kind, time.perf_counter())

    def _close_span(self, run_id) -> None:
        with self._lock:
            row = self._open.pop(run_id, None)
            if row is None:
                return
            name, kind, started = row
            self.spans.append({"name": name, "kind": kind,
                               "ms": round((time.perf_counter() - started) * 1000, 1)})

    # -- LangChain이 불러 주는 자리 ------------------------------------------------
    def on_chain_start(self, serialized, inputs, *, run_id, **kwargs) -> None:
        self._open_span(run_id, kwargs.get("name") or "chain", "chain")

    def on_chain_end(self, outputs, *, run_id, **kwargs) -> None:
        self._close_span(run_id)

    def on_chain_error(self, error, *, run_id, **kwargs) -> None:
        self._close_span(run_id)

    def on_retriever_start(self, serialized, query, *, run_id, **kwargs) -> None:
        self._open_span(run_id, kwargs.get("name") or "FaqRetriever", "retriever")

    def on_retriever_end(self, documents, *, run_id, **kwargs) -> None:
        self._close_span(run_id)

    def on_retriever_error(self, error, *, run_id, **kwargs) -> None:
        self._close_span(run_id)

    def on_tool_start(self, serialized, input_str, *, run_id, **kwargs) -> None:
        name = kwargs.get("name") or (serialized or {}).get("name") or "tool"
        self._open_span(run_id, name, "tool")

    def on_tool_end(self, output, *, run_id, **kwargs) -> None:
        self._close_span(run_id)

    def on_tool_error(self, error, *, run_id, **kwargs) -> None:
        self._close_span(run_id)

    # -- 읽기 --------------------------------------------------------------------
    def stages(self) -> dict:
        """단계 이름 → 밀리초. 돌지 않은 단계는 아예 들어가지 않습니다."""

        out: dict = {}
        for span in self.spans:
            key = self.STAGE_NAMES.get(span["name"])
            if key:
                out[key] = round(out.get(key, 0) + span["ms"], 1)
        return out

    def counts(self) -> dict:
        """체인이 실제로 돌았다는 증거. 보고서와 로그에 이 값을 씁니다."""

        steps = [span["name"] for span in self.spans if span["kind"] == "chain"]
        return {"chain_steps": len(steps), "step_names": steps,
                "retriever_calls": sum(1 for span in self.spans if span["kind"] == "retriever"),
                "tool_calls": sum(1 for span in self.spans if span["kind"] == "tool")}


def run(question: str, history: list | None = None, write=None) -> dict:
    """상담 한 건을 LangChain 체인에 태웁니다.

    write를 주면 답 쓰기까지 체인 안에서 끝납니다. 안 주면 경로 판단과 근거 수집까지만
    하고 answer는 None입니다. (평가 스크립트가 그렇게 씁니다)

    단계별 시간은 콜백에서 나옵니다. 어디가 느린지 뭉뚱그리면 고칠 곳을 못 찾습니다.
      analyze_ms 의도·조건 읽기          search_ms FAQ 검색(임베딩 호출 포함)
      route_ms   경로 판단               lookup_ms 공식 조회(바깥 API)
      llm_ms     답 쓰기                 chain_ms  체인 전체
    """

    timer = StageTimer()
    bundle = CHAIN.invoke({"question": question, "history": history, "write": write},
                          config={"callbacks": [timer], "run_name": "consult",
                                  "metadata": {"service": "consult"}})
    stages = timer.stages()
    evidence = bundle["evidence"]
    if bundle.get("answer") is None:
        # AI를 부르지 않은 경로입니다. 단계는 돌았지만 llm_ms로 적으면 오해를 부릅니다.
        stages.pop("llm_ms", None)
    # 답 쓰기를 뺀 시간. 예전 보고서와 견줄 수 있게 뜻을 그대로 둡니다.
    retrieval_ms = round(stages.get("chain_ms", 0) - stages.get("llm_ms", 0), 1)
    return {"plan": bundle["plan"], "documents": bundle["documents"], "evidence": evidence,
            "answer": bundle.get("answer"),
            "evidence_summary": consult_tools.summarize(evidence),
            "retrieval_ms": retrieval_ms, "stages": stages, "langchain": timer.counts()}
