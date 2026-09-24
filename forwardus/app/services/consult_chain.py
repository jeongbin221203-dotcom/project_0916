"""상담 처리 경로. LangChain(langchain-core)으로 엮습니다.

왜 LangChain인가 — 그리고 어디까지만 쓰는가
  이 프로젝트는 원래 httpx로 OpenAI를 직접 부릅니다. 그 호출을 통째로 바꾸면 이미 도는
  코드를 위험하게 건드리게 되고, langchain-openai를 붙이면 openai SDK까지 따라옵니다.
  그래서 langchain-core의 세 가지만 씁니다.
    BaseRetriever    FAQ 검색기를 LangChain 검색기로 노출 (faq_index 재사용)
    StructuredTool   공식 조회 함수를 입출력 스키마가 있는 도구로 노출 (consult_tools)
    Runnable         경로 판단 → 검색/도구 실행 → 답 생성을 하나의 체인으로 엮음
  답을 만드는 LLM 호출은 기존 ai_client를 RunnableLambda 안에서 부릅니다. 그래서
  LangChain 경로와 기존 경로가 두 번 부르는 일이 없습니다.

경로 (decide → run)
  faq_direct        전문가 승인(approved) FAQ + 조건 일치 + 최신 조회 불필요 → AI 없이 반환
  faq_context       FAQ를 근거로 AI가 답함 (미승인 자료는 '참고'로만 넘김)
  external_lookup   공식 도구 조회 후 그 근거로 AI가 답함
  clarification     조건이 모자라면 되물음 (AI 없이, 무엇이 필요한지 우리가 압니다)
  general_guidance  공식 근거를 못 얻었을 때 일반 안내 + 확인처 (규정 단정 금지)
"""

from __future__ import annotations

import re
import time

from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from langchain_core.runnables import RunnableLambda, RunnableParallel
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from app.services import consult_tools, faq_index

# 도구는 한 질문에 이만큼까지만 부릅니다. 같은 실패를 되풀이하지 않게 결과를 기억합니다.
MAX_TOOL_CALLS = 3
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

class FaqRetriever(BaseRetriever):
    """faq_index를 그대로 쓰는 LangChain 검색기. (색인을 두 벌 만들지 않습니다)"""

    k: int = 5

    def _get_relevant_documents(self, query: str, *,
                                run_manager: CallbackManagerForRetrieverRun | None = None
                                ) -> list[Document]:
        hits = faq_index.search(query, self.k)
        return [Document(page_content=faq_index.answer_text(faq),
                         metadata={"faq_id": faq["id"], "category": faq.get("category", ""),
                                   "score": score, "coverage": coverage, "similarity": similarity,
                                   "review_status": faq.get("review_status", ""),
                                   "freshness": faq.get("freshness", ""),
                                   "sources": faq.get("sources", []),
                                   "applicability": faq.get("applicability", {})})
                for faq, score, coverage, similarity in hits]


# --- 2. 공식 조회 함수를 LangChain 도구로 --------------------------------------------

class KoreaRequirementInput(BaseModel):
    hs_code: str = Field(description="한국 HSK 10자리 숫자. 6자리만 알면 빈 값으로 두세요.")


class RefundInput(BaseModel):
    hs_code: str = Field(description="한국 HSK 10자리 숫자")


class DestinationTariffInput(BaseModel):
    country_code: str = Field(description="수입국 2자리 코드 (US, JP 등)")
    hs_code: str = Field(description="HS 6자리 숫자")


class StatisticsInput(BaseModel):
    hs_code: str = Field(default="", description="HS 코드")
    country: str = Field(default="", description="상대국 이름 또는 코드")
    year: str = Field(default="", description="조회 연도(비우면 최근)")


TOOLS = [
    StructuredTool.from_function(
        func=consult_tools.korea_export_requirements, name="korea_export_requirements",
        description="한국에서 수출할 때 세관장확인대상인지(어떤 법령·기관·서류가 필요한지) 관세청에서 조회합니다. HSK 10자리 필요.",
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

def decide(question: str, history: list | None = None) -> dict:
    """어느 길로 갈지 정합니다. (AI를 부르기 전에, 우리 규칙으로)"""

    conditions = read_conditions(question, history)
    verdict = faq_index.decide(question)
    fresh = needs_fresh_lookup(question)
    faq = verdict.get("faq")
    approved = bool(faq) and (faq.get("review") or {}).get("review_status") == "approved"

    plan = {"route": "general_guidance", "conditions": conditions, "faq": faq,
            "candidates": verdict.get("candidates", ()), "needs_fresh": fresh,
            "faq_route": verdict["route"], "reasons": list(verdict.get("reasons", [])),
            "tool_calls": [], "approved": approved}

    if fresh:
        # 규정·세율을 지금 시점으로 물었습니다. FAQ가 있어도 공식 조회를 먼저 봅니다.
        plan["tool_calls"] = _plan_tools(question, conditions)
        if plan["tool_calls"]:
            plan["route"] = "external_lookup"
            return plan
        missing = _missing_for_lookup(conditions)
        korea_requirement = any(word in question for word in
                                ("요건", "세관장", "허가", "승인", "수출규제", "규제"))
        if korea_requirement and not conditions["hs10"]:
            # 관세청 수출요건 조회는 HSK 10자리라야 합니다. 6자리로는 못 봅니다.
            plan["route"] = "clarification"
            plan["missing"] = ["HSK 10자리 (관세청 수출요건 조회는 10자리라야 조회됩니다. "
                               "6자리까지는 나라 공통이고 뒤 4자리는 한국 세번입니다)"] + [
                item for item in missing if "HS" not in item]
            return plan
        if missing:
            plan["route"] = "clarification"
            plan["missing"] = missing
            return plan
        # 확인해 줄 공식 창구가 없는 질문입니다. 일반 안내로만 답하고 확인처를 댑니다.
        plan["route"] = "general_guidance"
        plan["reasons"].append("최신 확인이 필요한데 연결된 공식 조회 창구가 없습니다")
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

    missing = _missing_for_lookup(conditions)
    if missing and any(word in question for word in REGULATION_WORDS):
        plan["route"] = "clarification"
        plan["missing"] = missing
        return plan
    return plan


def _plan_tools(question: str, conditions: dict) -> list[dict]:
    """조건으로 실제 부를 수 있는 도구만 고릅니다. (없으면 빈 목록)"""

    calls: list[dict] = []
    lowered = question.lower()
    if conditions["hs10"]:
        if any(word in lowered for word in ("요건", "규제", "허가", "승인", "세관장", "인증", "금지", "제한")):
            calls.append({"tool": "korea_export_requirements",
                          "args": {"hs_code": conditions["hs10"]}})
        if "환급" in lowered:
            calls.append({"tool": "korea_refund_rate", "args": {"hs_code": conditions["hs10"]}})
    hs6 = conditions["hs6"] or conditions["hs10"][:6]
    for country in conditions["countries"]:
        if hs6 and country in ("US", "JP") and any(
                word in lowered for word in ("관세", "세율", "tariff", "hts")):
            calls.append({"tool": "destination_tariff",
                          "args": {"country_code": country, "hs_code": hs6}})
    return calls[:MAX_TOOL_CALLS]


def _missing_for_lookup(conditions: dict) -> list[str]:
    missing = []
    if not conditions["hs10"] and not conditions["hs6"]:
        missing.append("HS 코드(모르면 품명·재질·용도라도 알려 주세요)")
    if not conditions["countries"]:
        missing.append("어느 나라로 보내시나요")
    return missing


# --- 5. 실행 (LangChain Runnable) ----------------------------------------------------

def _run_tools(plan: dict) -> list[dict]:
    """계획한 도구를 부릅니다. 같은 도구·같은 인자는 한 번만, 전체 제한시간 안에서만."""

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
            evidence.append(tool.invoke(call["args"]))
        except Exception as error:                   # noqa: BLE001 - 조회 실패도 결과의 하나입니다
            evidence.append(consult_tools.evidence(
                status=consult_tools.FAILED, question_scope=call["args"],
                note=f"{call['tool']} 조회 실패: {type(error).__name__}"))
    return evidence


# LangChain 체인: 경로 판단 → (FAQ 검색 ∥ 공식 조회) → 근거 묶음
_retriever = FaqRetriever()

plan_step = RunnableLambda(lambda payload: decide(payload["question"], payload.get("history")),
                           name="decide_route")
gather_step = RunnableParallel(
    plan=RunnableLambda(lambda plan: plan, name="plan"),
    documents=RunnableLambda(
        lambda plan: _retriever.invoke(plan_question(plan)) if plan["route"] in
        ("faq_context", "external_lookup") else [], name="faq_retrieve"),
    evidence=RunnableLambda(_run_tools, name="official_lookup"),
)
CHAIN = plan_step | gather_step


def plan_question(plan: dict) -> str:
    faq = plan.get("faq") or {}
    return faq.get("question") or plan.get("question", "")


def run(question: str, history: list | None = None) -> dict:
    """상담 한 건을 LangChain 체인에 태웁니다. (AI 답 생성은 부르는 쪽에서)"""

    started = time.perf_counter()
    result = CHAIN.invoke({"question": question, "history": history or []})
    plan = result["plan"]
    plan["question"] = question
    evidence = result["evidence"]
    return {"plan": plan, "documents": result["documents"], "evidence": evidence,
            "evidence_summary": consult_tools.summarize(evidence),
            "retrieval_ms": round((time.perf_counter() - started) * 1000, 1)}
