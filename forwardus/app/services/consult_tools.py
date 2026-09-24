"""상담이 쓰는 공식 조회 도구. (LangChain StructuredTool로 감싸 씁니다)

무엇이 다른가
  우리가 이미 가진 수집기(collectors)는 성공/실패와 값만 돌려줍니다. 상담 답변에는
  "무슨 기관의 무슨 문서를, 언제 조회했고, 언제부터 적용되는 규정인지"가 함께 있어야
  합니다. 여기서 그 껍데기(Evidence)를 입힙니다.

상태(status) — 빈 결과를 '규제 없음'으로 읽지 않기 위해 다섯으로 나눕니다
  confirmed    공식 자료로 확인한 내용이 있습니다.
  need_more    조건이 더 있어야 조회됩니다. (예: HSK 10자리)
  not_found    조회는 됐는데 해당 자료가 없습니다. → '규제 없음'이 아닙니다.
  unsupported  우리가 연결하지 못한 범위입니다. (API 없음·권한 없음)
  failed       조회하다 실패했습니다. (망·인증·시간 초과)

지금 실제로 닿는 곳 (2026-09-24 확인)
  관세청 UNI-PASS  간이정액환급률·수출이행기간단축품목·항공사/포워더 부호  → 닿음
  관세청 UNI-PASS  세관장확인대상(수출요건 법령)                        → 인증키 불일치로 못 씀
  미국 USITC HTS · 일본 관세청 실행관세율표                              → 닿음
  WITS(세계은행) 관세                                                   → 이 망에서 실패
  mock 자료(customs_client.fetch_regulations)                            → 근거로 쓰지 않습니다
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone

CONFIRMED = "confirmed"
NEED_MORE = "need_more"
NOT_FOUND = "not_found"
UNSUPPORTED = "unsupported"
FAILED = "failed"

# 도구 하나가 이보다 오래 걸리면 상담을 붙잡아 둡니다.
TOOL_TIMEOUT = 25
HSK10 = re.compile(r"^\d{10}$")


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _hash(payload) -> str:
    return hashlib.sha256(str(payload).encode("utf-8")).hexdigest()[:12]


def evidence(*, status: str, question_scope: dict, agency: str = "", document: str = "",
             url: str = "", excerpt: str = "", rows=None, dates: dict | None = None,
             note: str = "") -> dict:
    """근거 한 덩어리. 날짜는 자료에 있는 것만 채우고 없으면 비워 둡니다.

    '오늘 조회했다'는 retrieved_at일 뿐, 그 자료가 최신이라는 뜻이 아닙니다.
    그래서 effective_from / revised_on 이 비어 있으면 화면에도 비워서 보여 줍니다.
    """

    return {"status": status, "scope": question_scope, "agency": agency, "document": document,
            "url": url, "excerpt": excerpt[:600], "rows": rows or [],
            "dates": {"published_on": (dates or {}).get("published_on", ""),
                      "revised_on": (dates or {}).get("revised_on", ""),
                      "effective_from": (dates or {}).get("effective_from", ""),
                      "effective_to": (dates or {}).get("effective_to", ""),
                      "retrieved_at": _now()},
            "content_hash": _hash(rows or excerpt), "note": note}


# --- 1. 한국 수출요건 (세관장확인대상) ------------------------------------------------

def korea_export_requirements(hs_code: str) -> dict:
    """한국에서 내보낼 때 세관장이 확인하는 품목인지, 어느 법령·기관인지.

    관세청 UNI-PASS 'ccctLworCdQry'를 씁니다. HSK 10자리가 있어야 합니다.
    (6자리 HS는 나라마다 뒤가 달라 그대로 쓸 수 없습니다)
    """

    from app.collectors import customs_extra_client

    digits = "".join(ch for ch in str(hs_code or "") if ch.isdigit())
    scope = {"country": "KR", "direction": "export", "hs_code": digits}
    if not HSK10.match(digits):
        return evidence(status=NEED_MORE, question_scope=scope,
                        agency="관세청", document="세관장확인대상 법령 조회",
                        url="https://unipass.customs.go.kr",
                        note="HSK 10자리가 필요합니다. 6자리까지는 나라 공통이지만 뒤 4자리는 "
                             "한국 세번이라, 품명·용도·재질을 알아야 정해집니다.")

    result = customs_extra_client.export_requirement_laws(digits)
    if result["success"]:
        rows = result["data"]
        return evidence(status=CONFIRMED if rows else NOT_FOUND, question_scope=scope,
                        agency="관세청", document="세관장확인대상 법령코드 조회(ccctLworCdQry)",
                        url="https://unipass.customs.go.kr", rows=rows,
                        dates={"effective_from": (rows[0].get("start_date") if rows else ""),
                               "effective_to": (rows[0].get("end_date") if rows else "")},
                        note="" if rows else "이 조회에서 걸리는 법령이 나오지 않았습니다. "
                                             "'수출 규제가 없다'는 뜻이 아니라 이 조회 범위에서 "
                                             "안 나왔다는 뜻입니다. 품목분류가 맞는지 함께 확인하세요.")
    # 인증키가 그 서비스용이 아니면 여기로 옵니다. 못 쓴다고 그대로 말합니다.
    message = result.get("message", "")
    unsupported = "인증키" in message or result.get("error_code") == "API_AUTH_FAILED"
    return evidence(status=UNSUPPORTED if unsupported else FAILED, question_scope=scope,
                    agency="관세청", document="세관장확인대상 법령코드 조회(ccctLworCdQry)",
                    url="https://unipass.customs.go.kr",
                    note=f"조회하지 못했습니다: {message} "
                         "이 서비스는 UNI-PASS에서 따로 신청한 인증키가 있어야 합니다"
                         "(.env의 UNIPASS_KEY_REQUIREMENT_APPROVAL). 확인 전까지는 요건 유무를 "
                         "단정할 수 없습니다.")


# --- 2. 간이정액환급률 ---------------------------------------------------------------

def korea_refund_rate(hs_code: str) -> dict:
    """수출 뒤 돌려받는 간이정액환급액(공고 단가). 중소기업 환급 실무에서 씁니다."""

    from app.collectors import customs_extra_client

    digits = "".join(ch for ch in str(hs_code or "") if ch.isdigit())
    scope = {"country": "KR", "direction": "export", "hs_code": digits}
    if not HSK10.match(digits):
        return evidence(status=NEED_MORE, question_scope=scope, agency="관세청",
                        document="간이정액환급률표", url="https://unipass.customs.go.kr",
                        note="HSK 10자리가 필요합니다.")
    result = customs_extra_client.refund_rate(digits)
    if not result["success"]:
        return evidence(status=FAILED, question_scope=scope, agency="관세청",
                        document="간이정액환급률표", url="https://unipass.customs.go.kr",
                        note=result.get("message", ""))
    rows = result["data"]
    return evidence(status=CONFIRMED if rows else NOT_FOUND, question_scope=scope,
                    agency="관세청", document="간이정액환급률표(simlXamrttXtrnUserQry)",
                    url="https://unipass.customs.go.kr", rows=rows,
                    dates={"effective_from": rows[0].get("start_date", "") if rows else ""},
                    note="" if rows else "이 세번으로 공고된 간이정액환급액이 조회되지 않았습니다.")


# --- 3. 수입국 관세 (미국·일본) -------------------------------------------------------

def destination_tariff(country_code: str, hs_code: str) -> dict:
    """수입국의 관세율표에서 해당 세번 줄을 찾아 옵니다.

    지금 닿는 곳은 미국(USITC HTS)과 일본(관세청 실행관세율표)뿐입니다.
    다른 나라는 unsupported로 답하고 확인처를 안내합니다. (WITS는 이 망에서 실패)
    """

    from app.collectors import tariff_client

    country = str(country_code or "").upper()[:2]
    digits = "".join(ch for ch in str(hs_code or "") if ch.isdigit())
    scope = {"country": country, "direction": "import", "hs_code": digits}
    if len(digits) < 4:
        return evidence(status=NEED_MORE, question_scope=scope,
                        note="HS 6자리(최소 4자리)가 필요합니다.")

    if country == "US":
        result = tariff_client.fetch_us_hts(digits[:6])
        if not result["success"]:
            return evidence(status=FAILED, question_scope=scope, agency="USITC",
                            document="Harmonized Tariff Schedule",
                            url="https://hts.usitc.gov", note=result.get("message", ""))
        rows = result["data"][:12]
        return evidence(status=CONFIRMED if rows else NOT_FOUND, question_scope=scope,
                        agency="USITC (미국 국제무역위원회)", document="HTS 관세율표",
                        url=f"https://hts.usitc.gov/search?query={digits[:6]}", rows=rows,
                        excerpt=" / ".join(str(row.get("description", ""))[:120] for row in rows[:3]),
                        note="일반세율(General)과 한-미 FTA 특혜세율은 줄마다 다릅니다. "
                             "특혜를 받으려면 원산지 기준 충족과 증명이 따로 필요합니다.")
    if country == "JP":
        result = tariff_client.fetch_japan_tariff(digits[:4])
        if not result["success"]:
            return evidence(status=FAILED, question_scope=scope, agency="일본 관세청",
                            document="실행관세율표", url="https://www.customs.go.jp",
                            note=result.get("message", ""))
        data = result["data"]
        rows = (data.get("lines") or [])[:12]
        return evidence(status=CONFIRMED if rows else NOT_FOUND, question_scope=scope,
                        agency="일본 관세청(Japan Customs)", document="실행관세율표(Tariff Schedule)",
                        url="https://www.customs.go.jp/english/tariff/", rows=rows,
                        dates={"revised_on": data.get("edition", "")},
                        note="표의 판(edition) 날짜를 함께 보세요. 협정세율(EPA/RCEP)은 원산지 "
                             "증명이 있어야 적용됩니다.")
    return evidence(status=UNSUPPORTED, question_scope=scope,
                    note=f"{country} 관세율은 아직 공식 조회를 연결하지 못했습니다. "
                         "관세청 FTA포털·TradeNAVI·해당국 세관에서 확인해야 합니다.")


# --- 4. 수출 실적·결제 통계 (이미 있는 도구 재사용) -----------------------------------

def trade_statistics(hs_code: str = "", country: str = "", year: str = "") -> dict:
    """관세청 품목별 수출실적. (trade_insight_service의 도구를 그대로 씁니다)"""

    from app.services import trade_insight_service

    scope = {"country": country, "hs_code": hs_code, "year": year}
    try:
        output = trade_insight_service.run_tool(
            "get_item_trade_statistics",
            {k: v for k, v in {"hs_code": hs_code, "country": country,
                               "target_year": year}.items() if v})
    except Exception as error:                       # noqa: BLE001
        return evidence(status=FAILED, question_scope=scope, note=str(error)[:200])
    if not output.get("success"):
        return evidence(status=FAILED, question_scope=scope, agency="관세청",
                        document="품목별 수출입실적", note=str(output.get("message", ""))[:200])
    return evidence(status=CONFIRMED, question_scope=scope, agency="관세청",
                    document="품목별 수출입실적", url="https://unipass.customs.go.kr",
                    rows=(output.get("rows") or [])[:20],
                    dates={"published_on": str(output.get("period", ""))},
                    note="통계는 규정이 아닙니다. 요건·세율 판단의 근거로 쓰지 마세요.")


# 상담이 쓸 수 있는 도구 목록. LangChain StructuredTool로 감싸는 것은 consult_chain에서 합니다.
REGISTRY = {
    "korea_export_requirements": korea_export_requirements,
    "korea_refund_rate": korea_refund_rate,
    "destination_tariff": destination_tariff,
    "trade_statistics": trade_statistics,
}


def summarize(items: list[dict]) -> dict:
    """여러 근거를 한 줄로. 화면과 평가가 같은 기준으로 읽게 합니다."""

    statuses = [item["status"] for item in items]
    return {"count": len(items),
            "confirmed": statuses.count(CONFIRMED),
            "unsupported": statuses.count(UNSUPPORTED),
            "failed": statuses.count(FAILED),
            "not_found": statuses.count(NOT_FOUND),
            "need_more": statuses.count(NEED_MORE),
            # 확인된 근거가 하나도 없으면 규정에 대한 결론을 내면 안 됩니다.
            "may_conclude": statuses.count(CONFIRMED) > 0}
