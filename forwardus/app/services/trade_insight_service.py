"""메인 '무역 상담' 챗봇이 부르는 데이터 도구 (OpenAI Function Calling).

"의류 수출하고 싶은데 국가 추천해줘", "OO 수출액 비교해줘", "베트남 결제 리스크 어때?"
같은 질문에 AI가 기억으로 답하지 않고, 공공데이터 API에서 실제 수치를 받아 답하게 합니다.

    fetch_customs_export_stats(item_name, target_year, hs_codes)
        관세청 품목별·국가별 수출입실적(GW) → 연간 수출액, 전년 대비 증감률, 주요 수출국
    fetch_ksure_payment_risk(country_name)
        한국무역보험공사 수출결제정보 → 결제방식 비중, 평균 결제기간, 연체율, 참고 위험 등급

    get_item_trade_statistics(item_name, hs_code, period)
        관세청 품목별 수출입실적(GW) → K-stat 품목별 표 (순위·HS코드·품목명·전년 실적·
        당해 수출액·증감률·무역수지, 천 달러)

두 API 모두 공공데이터포털 키 하나(DATA_GO_KR_SERVICE_KEY)로 부릅니다.

**숫자는 우리 코드가 계산합니다.** 합계·증감률·비중·억 달러 환산을 AI에게 맡기면
틀립니다. 도구 결과에 계산을 마친 값과 읽기 좋은 글자("2억 7,174만 달러")를 함께 넣어,
AI는 옮겨 적고 해석만 하게 합니다.

**없는 것은 없다고 돌려줍니다.** 키가 없거나 API가 멈추면 success=False와 이유를
돌려주고, 프롬프트가 "조회하지 못했다"고 말하게 합니다. 지어낸 수치로 채우지 않습니다.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import date

from app.collectors import hsk_catalog, ksure_client, trade_stats_client

MAX_HS_CODES = 3
TOP_DEFAULT = 5
TOP_MAX = 10
# 성장 국가로 꼽으려면 이 정도는 팔려야 합니다. 작은 시장의 +19,000%(리비아)는 뜻이 없습니다.
RISING_MIN_SHARE = 1.0          # 올해 전체 수출의 1% 이상이고
RISING_MIN_PREV_USD = 100_000   # 지난해에도 10만 달러 이상 나간 나라
# 수출 실적 상위 몇 나라에 결제 통계 요약을 붙일지.
PAYMENT_PREVIEW = 3

CUSTOMS_SOURCE = "관세청 품목별·국가별 수출입실적(GW) · 공공데이터포털"
KSURE_SOURCE = "한국무역보험공사 수출결제정보 · 공공데이터포털"
# 같은 관세청 API(nitemtrade)를 품목 쪽에서 본 것입니다. K-stat 품목별 수출입실적과 같은 표입니다.
ITEM_SOURCE = "관세청 품목별 수출입실적(GW) · 공공데이터포털"
RISK_BASIS = ("ForwardUs가 무역보험공사 연체율·장기결제 비중을 전체 나라 평균과 비교해 매긴 "
              "참고 등급입니다. 무역보험공사의 공식 국가등급이 아닙니다.")


# --- 공통 -------------------------------------------------------------------------

def _usd_text(value: float) -> str:
    """사람이 읽는 달러. 1억 이상은 억, 1만 이상은 만 단위로."""

    value = float(value or 0)
    if abs(value) >= 1e8:
        eok, man = divmod(round(value / 1e4), 10_000)
        return f"{int(eok):,}억 {int(man):,}만 달러" if man else f"{int(eok):,}억 달러"
    if abs(value) >= 1e4:
        return f"{round(value / 1e4):,}만 달러"
    return f"{value:,.0f}달러"


def _pct(new: float, old: float) -> float | None:
    if not old:
        return None
    return round((new - old) / old * 100, 1)


def _signed(value: float | None) -> str:
    return "비교 불가(전년 실적 없음)" if value is None else f"{value:+.1f}%"


def _fail(message: str, code: str = "API_NO_DATA", **extra) -> dict:
    return {"success": False, "error_code": code, "message": message, **extra}


# --- 관세청: 품목별 국가별 수출 실적 ----------------------------------------------------

# 범위가 넓어 품목표 검색으로는 엉뚱한 호가 잡히는 품목. ("화장품" → 4202 화장품 가방)
# 무역통계에서 흔히 묶어 보는 범위를 굳혀 둡니다.
BROAD_ITEMS = {
    "의류": ["61", "62"], "옷": ["61", "62"], "패션": ["61", "62"], "봉제의류": ["61", "62"],
    "니트": ["61"], "편직의류": ["61"],
    "화장품": ["3304"], "기초화장품": ["3304"], "색조화장품": ["3304"], "k뷰티": ["3304"],
    "향수": ["3303"], "헤어제품": ["3305"], "샴푸": ["3305"],
    "반도체": ["8541", "8542"], "메모리": ["8542"],
    "자동차": ["8703"], "자동차부품": ["8708"], "차부품": ["8708"],
    "타이어": ["4011"], "배터리": ["8507"], "이차전지": ["8507"],
    "신발": ["64"], "가방": ["4202"], "안경": ["9004"],
    "라면": ["1902"], "김": ["2008", "1212"], "김치": ["2005"], "소주": ["2208"], "과자": ["1905"],
    "커피": ["2101"], "음료": ["2202"],
    "의료기기": ["9018"], "철강": ["72"], "플라스틱": ["39"],
}
# 품목표 검색 결과가 이만큼 한 호에 몰려야 그 호로 봅니다. 아니면 짐작하지 않고 되묻습니다.
CATALOG_DOMINANCE = 0.5


def resolve_hs(item_name: str, hs_codes=None) -> dict:
    """무엇으로 조회할지. AI가 준 HS부호를 먼저 쓰되 품목표에 있는 부호인지 확인합니다.

    부호가 없으면 넓은 품목 표(BROAD_ITEMS) → 품목표(HSK) 검색 순서로 찾습니다.
    검색 결과가 여러 호에 흩어지면(의류·반도체처럼) 하나를 짐작하지 않고
    basis="ambiguous"와 후보를 돌려줍니다. AI가 hs_codes를 넣어 다시 부릅니다.
    """

    given = hs_codes if isinstance(hs_codes, list) else ([hs_codes] if hs_codes else [])
    codes, rejected = [], []
    for raw in given[:MAX_HS_CODES * 2]:
        digits = "".join(ch for ch in str(raw) if ch.isdigit())
        digits = digits[:6] if len(digits) >= 6 else digits[:4] if len(digits) >= 4 else digits[:2]
        if len(digits) < 2 or digits in [code for code, _ in codes]:
            continue
        name = hsk_catalog.level_name(digits)
        if name is None:
            rejected.append(digits)
            continue
        codes.append((digits, name))
    if codes:
        return {"codes": codes[:MAX_HS_CODES], "basis": "given", "rejected": rejected}

    key = "".join(str(item_name or "").lower().split())
    if key in BROAD_ITEMS:
        return {"codes": [(code, hsk_catalog.level_name(code) or "") for code in BROAD_ITEMS[key]],
                "basis": "broad", "rejected": rejected}

    results = hsk_catalog.search(item_name or "", limit=400) or []
    if not results:
        return {"codes": [], "basis": "none", "rejected": rejected}
    headings = Counter(row["code"].replace(".", "").replace("-", "")[:4] for row in results)
    ranked = headings.most_common(5)
    top, hits = ranked[0]
    candidates = [{"hs_code": code, "name": hsk_catalog.level_name(code) or "", "matches": count}
                  for code, count in ranked]
    if hits / len(results) < CATALOG_DOMINANCE:
        return {"codes": [], "basis": "ambiguous", "candidates": candidates, "rejected": rejected}
    return {"codes": [(top, hsk_catalog.level_name(top) or "")], "basis": "catalog",
            "alternatives": candidates[1:], "rejected": rejected}


def _year(target_year) -> int:
    this_year = date.today().year
    try:
        year = int(str(target_year).strip()[:4])
    except (TypeError, ValueError):
        return this_year - 1
    return year if 2000 <= year <= this_year else this_year - 1


def _merge(results: list[dict]) -> dict:
    """HS부호 여럿(예: 의류 61류 + 62류)을 나라별로 더합니다."""

    countries: dict[str, dict] = {}
    total = 0
    last_month = ""
    for data in results:
        total += data["total_export_usd"]
        last_month = max(last_month, data["last_month"])
        for code, row in data["countries"].items():
            found = countries.setdefault(code, {**row, "export_usd": 0, "export_weight_kg": 0})
            found["export_usd"] += row["export_usd"]
            found["export_weight_kg"] += row["export_weight_kg"]
    return {"countries": countries, "total_export_usd": total, "last_month": last_month}


def _period(year: int, last_month: int) -> str:
    return f"{year}년 1~{last_month}월" if last_month < 12 else f"{year}년 연간(1~12월)"


def _payment_brief(country: str) -> dict:
    """수출 실적 표 옆에 붙일 결제 통계 요약. 자세한 것은 fetch_ksure_payment_risk로 봅니다."""

    full = fetch_ksure_payment_risk(country)
    if not full["success"]:
        return {"available": False, "message": full["message"]}
    bench = full["benchmark_all_countries"] or {}
    return {
        "available": True, "year": full["year"], "risk_level": full["risk_level"],
        "late_payment_rate_pct": full["late_payment_rate_pct"],
        "all_countries_late_payment_rate_pct": bench.get("late_payment_rate_pct"),
        "average_payment_days": full["average_payment_days"],
        "all_countries_average_payment_days": bench.get("average_payment_days"),
        "main_payment_terms": [{"name": row["name"], "share_pct": row["share_pct"]}
                               for row in full["payment_terms"][:3]],
        "lc_share_pct": next((row["share_pct"] for row in full["payment_terms"]
                              if row["name"] == "L/C"), None),
        "cautions": full["cautions"][:3],
    }


def fetch_customs_export_stats(item_name: str = "", target_year=None, hs_codes=None,
                               top: int = TOP_DEFAULT, with_payment_risk: bool = True) -> dict:
    """품목의 국가별 수출액, 전년 대비 증감률, 주요 수출국 Top N.

    올해처럼 끝나지 않은 해를 고르면 자료가 있는 마지막 달까지 보고, 지난해도 같은 달까지만
    더해 견줍니다. (1~8월을 지난해 12개월과 견주면 모두 역성장으로 보입니다)
    """

    if not trade_stats_client.available():
        return _fail("관세청 무역통계 키(DATA_GO_KR_SERVICE_KEY)가 없어 조회하지 못했습니다.",
                     "API_AUTH_FAILED")
    hs = resolve_hs(item_name, hs_codes)
    if hs["basis"] == "ambiguous":
        # 짐작하지 않습니다. AI가 품목에 맞는 부호를 골라 hs_codes로 다시 부르게 합니다.
        return _fail(f"'{item_name}'은(는) HS 범위가 넓어 한 호로 정할 수 없습니다. 품목에 맞는 HS부호 "
                     "2·4자리를 hs_codes에 넣어 이 도구를 다시 부르세요. 품목표 검색 후보는 "
                     "candidates에 있습니다(검색에 걸린 수 기준이라 참고만 하세요).",
                     "HS_AMBIGUOUS", candidates=hs["candidates"])
    if not hs["codes"]:
        return _fail(f"'{item_name}'에 맞는 HS부호를 찾지 못했습니다. 품목에 맞는 HS부호 2·4자리를 "
                     "hs_codes에 넣어 다시 부르거나, 사용자에게 품명을 더 구체적으로(예: 면 티셔츠) 물어보세요.",
                     "VALIDATION_ERROR", rejected_hs_codes=hs["rejected"])
    top = max(1, min(int(top or TOP_DEFAULT), TOP_MAX))
    year = _year(target_year)

    def collect(y: int, end_month: int = 12) -> dict:
        parts = []
        for code, _ in hs["codes"]:
            result = trade_stats_client.exports_by_country(code, f"{y}01", f"{y}{end_month:02d}")
            if not result["success"]:
                return result
            parts.append(result["data"])
        return {"success": True, "data": _merge(parts)}

    current = collect(year)
    if current["success"] and not current["data"]["countries"] and year == date.today().year:
        # 1월 초에는 올해 자료가 아직 없습니다. 지난해로 내려갑니다.
        year -= 1
        current = collect(year)
    if not current["success"]:
        return _fail(current.get("message") or "관세청 무역통계를 받지 못했습니다.",
                     current.get("error_code") or "API_ERROR")
    now = current["data"]
    if not now["countries"]:
        return _fail(f"{year}년 HS {', '.join(c for c, _ in hs['codes'])} 수출 실적이 없습니다.")

    try:
        last_month = int(now["last_month"].split(".")[1]) if now["last_month"] else 12
    except (IndexError, ValueError):
        last_month = 12
    previous = collect(year - 1, last_month)
    before = previous["data"] if previous["success"] else {"countries": {}, "total_export_usd": 0}

    total = now["total_export_usd"] or sum(row["export_usd"] for row in now["countries"].values())
    rows = []
    for code, row in now["countries"].items():
        if row["export_usd"] <= 0:
            continue
        old = (before["countries"].get(code) or {}).get("export_usd", 0)
        growth = _pct(row["export_usd"], old)
        rows.append({
            "country": row["country"], "country_code": code,
            "export_usd": row["export_usd"], "export_usd_text": _usd_text(row["export_usd"]),
            "share_pct": round(row["export_usd"] / total * 100, 1) if total else None,
            "prev_export_usd": old, "prev_export_usd_text": _usd_text(old),
            "yoy_pct": growth, "yoy_text": _signed(growth),
        })
    rows.sort(key=lambda row: -row["export_usd"])
    for rank, row in enumerate(rows, 1):
        row["rank"] = rank

    # 상위 나라에는 무역보험공사 결제 통계 요약을 붙입니다. AI가 결제 도구를 부르지 않고
    # 결제 주의점을 "기억으로" 쓰는 일을 막습니다. (실제로 연체율을 지어낸 적이 있습니다)
    if with_payment_risk:
        for row in rows[:PAYMENT_PREVIEW]:
            row["payment_risk"] = _payment_brief(row["country"])

    rising = [row for row in rows if row["yoy_pct"] is not None and row["yoy_pct"] > 0
              and (row["share_pct"] or 0) >= RISING_MIN_SHARE
              and row["prev_export_usd"] >= RISING_MIN_PREV_USD]
    rising.sort(key=lambda row: -row["yoy_pct"])
    prev_total = before["total_export_usd"]
    world_growth = _pct(total, prev_total)

    with_ksure = any((row.get("payment_risk") or {}).get("available") for row in rows)
    result = {
        "success": True,
        "source": CUSTOMS_SOURCE + (f" + {KSURE_SOURCE}" if with_ksure else ""),
        "item_name": item_name,
        "hs_codes": [{"hs_code": code, "name": name} for code, name in hs["codes"]],
        "hs_basis": {"given": "AI가 고른 HS부호를 품목표에서 확인해 썼습니다.",
                     "broad": "무역통계에서 이 품목을 흔히 묶어 보는 HS 범위로 조회했습니다.",
                     "catalog": "품목표(HSK)에서 품명으로 찾은 호(4자리)를 썼습니다. 품목이 다르면 "
                                "HS부호를 알려 달라고 안내하세요."}[hs["basis"]],
        "period": _period(year, last_month),
        "compare_period": _period(year - 1, last_month),
        "partial_year": last_month < 12,
        "total_export_usd": total, "total_export_text": _usd_text(total),
        "prev_total_export_usd": prev_total, "prev_total_export_text": _usd_text(prev_total),
        "total_yoy_pct": world_growth, "total_yoy_text": _signed(world_growth),
        "country_count": len(rows),
        "top_countries": rows[:top],
        "fastest_growing": rising[:3],
        "unit": "달러(USD). 관세청 수출신고 기준 통관 실적입니다.",
        "payment_risk_note": (f"상위 {PAYMENT_PREVIEW}개국의 payment_risk는 한국무역보험공사 수출결제정보 "
                              "요약입니다. 결제 주의점은 이 값만 근거로 쓰고, 다른 나라의 결제 조건이 "
                              "필요하면 fetch_ksure_payment_risk를 부르세요."),
    }
    if hs.get("alternatives"):
        result["hs_alternatives"] = hs["alternatives"]
    if hs["rejected"]:
        result["rejected_hs_codes"] = hs["rejected"]
    if not previous["success"]:
        result["compare_note"] = "전년 실적을 받지 못해 증감률을 계산하지 못했습니다."
    return result


# --- 관세청: 품목별 수출입 실적 (K-stat 품목별 표) ----------------------------------------

ITEM_TOP_DEFAULT = 10
ITEM_TOP_MAX = 20
# 관세청 품명은 법조문 그대로라 깁니다. 표에는 괄호 속 설명을 뗀 짧은 이름을 씁니다.
SHORT_NAME_CHARS = 40


def _kusd(value: float) -> int:
    """달러 → 천 달러(천불). K-stat 표와 같은 단위로 맞춥니다. 반올림은 여기서 한 번만."""

    return int(round(float(value or 0) / 1000))


def _comma(value: int) -> str:
    return f"{value:,}"


def _short_name(name: str) -> str:
    """"메모리[…]" → "메모리". 괄호 속 설명을 떼고 너무 길면 줄입니다."""

    text = str(name or "").strip()
    for _ in range(3):      # 괄호가 겹쳐 있는 경우가 있습니다.
        text = re.sub(r"\([^()]*\)|\[[^\[\]]*\]", "", text)
    text = re.sub(r"\s+", " ", text).strip(" ,ㆍ·") or str(name or "").strip()
    return text if len(text) <= SHORT_NAME_CHARS else text[:SHORT_NAME_CHARS - 1] + "…"


# 이 이름만으로는 무슨 품목인지 알 수 없습니다. 어느 호 아래의 것인지 붙여 보여 줍니다.
GENERIC_NAMES = {"기타", "그 밖의 것", "부분품", "부속품", "가루", "그 밖의 방직용 섬유로 만든 것"}


def _display_name(name: str, group: str) -> str:
    """"기타" → "기타 (3304)". AI에게 맡기면 빠뜨려서 우리가 붙입니다."""

    short = _short_name(name)
    return f"{short} ({group})" if short in GENERIC_NAMES or len(short) <= 2 else short


def _item_period(period, today: date | None = None) -> tuple[int, bool]:
    """(해, 올해 누계인지). "latest"·빈 값 → 최근 완결 연도, "ytd"·"누계" → 올해 누계, "2024" → 그 해."""

    today = today or date.today()
    text = str(period or "").strip().lower()
    if text in ("ytd", "누계", "올해", "올해누계", "당해", "current", str(today.year)):
        return today.year, True
    if text.isdigit() and 2000 <= int(text) < today.year:
        return int(text), False
    return today.year - 1, False


def get_item_trade_statistics(item_name: str = "", hs_code: str = "", period: str = "latest",
                              top: int = ITEM_TOP_DEFAULT) -> dict:
    """K-stat 품목별 수출입실적처럼, 품목(군) 아래 세부 품목의 순위·전년 실적·당해 수출액·
    증감률·무역수지를 돌려줍니다. 금액은 천 달러(천불)입니다.

    "메모리"를 물으면 8542(전자집적회로) 아래 6자리(프로세서·메모리·증폭기…)가,
    "의류"를 물으면 61·62류 아래 4자리 호들이 한 표에 순위대로 들어갑니다.
    올해 누계는 자료가 있는 마지막 달까지, 전년도 같은 달까지만 더해 견줍니다.
    """

    if not trade_stats_client.available():
        return _fail("관세청 무역통계 키(DATA_GO_KR_SERVICE_KEY)가 없어 조회하지 못했습니다.",
                     "API_AUTH_FAILED")
    hs = resolve_hs(item_name, [hs_code] if hs_code else None)
    if hs["basis"] == "ambiguous":
        return _fail(f"'{item_name}'은(는) HS 범위가 넓어 한 호로 정할 수 없습니다. 품목에 맞는 HS부호 "
                     "2·4자리를 hs_code에 넣어 이 도구를 다시 부르세요.",
                     "HS_AMBIGUOUS", candidates=hs["candidates"])
    if not hs["codes"]:
        return _fail(f"'{item_name}'에 맞는 HS부호를 찾지 못했습니다. HS부호 2·4자리를 hs_code에 넣어 "
                     "다시 부르거나, 사용자에게 품명을 더 구체적으로 물어보세요.", "VALIDATION_ERROR")
    top = max(1, min(int(top or ITEM_TOP_DEFAULT), ITEM_TOP_MAX))
    year, ytd = _item_period(period)

    def collect(y: int, end_month: int = 12) -> dict:
        parts = []
        for code, _ in hs["codes"]:
            result = trade_stats_client.exports_by_country(code, f"{y}01", f"{y}{end_month:02d}")
            if not result["success"]:
                return result
            parts.append(result["data"])
        return {"success": True, "data": parts}

    current = collect(year)
    if current["success"] and ytd and not any(part["codes"] for part in current["data"]):
        # 1월 초에는 올해 자료가 아직 없습니다. 최근 완결 연도로 내려갑니다.
        year, ytd = year - 1, False
        current = collect(year)
    if not current["success"]:
        return _fail(current.get("message") or "관세청 무역통계를 받지 못했습니다.",
                     current.get("error_code") or "API_ERROR")
    now = current["data"]
    last = max((part["last_month"] for part in now), default="")
    if not last:
        return _fail(f"{year}년 HS {', '.join(c for c, _ in hs['codes'])} 실적이 없습니다.")
    try:
        last_month = int(last.split(".")[1])
    except (IndexError, ValueError):
        last_month = 12
    previous = collect(year - 1, last_month)
    before: dict[str, dict] = {}
    prev_total = 0
    if previous["success"]:
        for part in previous["data"]:
            before.update(part["codes"])
            prev_total += part["total_export_usd"]

    rows = []
    for part in now:
        for code, line in part["codes"].items():
            old = (before.get(code) or {}).get("export_usd", 0)
            growth = _pct(line["export_usd"], old)
            export, imports, prev = _kusd(line["export_usd"]), _kusd(line["import_usd"]), _kusd(old)
            balance = export - imports
            rows.append({
                # 세부 품목명이 "기타"처럼 짧으면 어느 호 아래의 것인지 함께 봐야 뜻이 통합니다.
                "hs_code": code, "group_hs_code": part["hs_code"],
                "name": _display_name(line["name"], part["hs_code"]), "name_full": line["name"],
                "prev_export_kusd": prev, "prev_export_text": _comma(prev),
                "export_kusd": export, "export_text": _comma(export),
                "yoy_pct": growth, "yoy_text": _signed(growth),
                "import_kusd": imports,
                "trade_balance_kusd": balance, "trade_balance_text": f"{balance:,}",
            })
    rows = [row for row in rows if row["export_kusd"] or row["prev_export_kusd"]]
    rows.sort(key=lambda row: -row["export_kusd"])
    for rank, row in enumerate(rows, 1):
        row["rank"] = rank

    total_export = sum(part["total_export_usd"] for part in now)
    total_import = sum(part.get("total_import_usd", 0) for part in now)
    total_growth = _pct(total_export, prev_total)
    total_balance = _kusd(total_export) - _kusd(total_import)
    return {
        "success": True, "source": ITEM_SOURCE,
        "item_name": item_name,
        "hs_codes": [{"hs_code": code, "name": _short_name(name)} for code, name in hs["codes"]],
        "hs_basis": {"given": "AI가 고른 HS부호를 품목표에서 확인해 썼습니다.",
                     "broad": "무역통계에서 이 품목을 흔히 묶어 보는 HS 범위로 조회했습니다.",
                     "catalog": "품목표(HSK)에서 품명으로 찾은 호(4자리)를 썼습니다."}[hs["basis"]],
        "period": _period(year, last_month) + (" 누계" if last_month < 12 else ""),
        "compare_period": _period(year - 1, last_month),
        "partial_year": last_month < 12,
        "unit": "천 달러(천불). 관세청 달러 금액을 1,000으로 나눠 반올림한 값입니다.",
        "total": {
            "export_kusd": _kusd(total_export), "export_text": _comma(_kusd(total_export)),
            "export_usd_text": _usd_text(total_export),
            "prev_export_kusd": _kusd(prev_total), "prev_export_text": _comma(_kusd(prev_total)),
            "yoy_pct": total_growth, "yoy_text": _signed(total_growth),
            "import_kusd": _kusd(total_import),
            "trade_balance_kusd": total_balance, "trade_balance_text": f"{total_balance:,}",
        },
        "item_count": len(rows),
        "rows": rows[:top],
        "table_columns": ["순위", "HS코드", "품목명", "전년 실적(천불)", "당해연도 수출액(천불)",
                          "증감률", "무역수지(천불)"],
    }


# --- 무역보험공사: 나라별 결제 동향 ------------------------------------------------------

def _latest(series: list[dict]) -> dict | None:
    return series[-1] if series else None


def _value(series: list[dict], back: int = 0) -> float | None:
    return series[-1 - back]["value"] if len(series) > back else None


def _shares(groups: list[dict]) -> list[dict]:
    rows = []
    for group in groups:
        if not group["series"]:
            continue
        rows.append({"name": group["name"], "code": group["code"],
                     "share_pct": _value(group["series"]),
                     "prev_share_pct": _value(group["series"], 1),
                     "year": group["series"][-1]["year"]})
    return rows


def _grade(late: float | None, bench: float | None, long_tail: float | None,
           late_days: float | None, bench_days: float | None) -> str:
    if late is None or not bench:
        return "판단 불가"
    levels = ["낮음", "보통", "주의", "높음"]
    ratio = late / bench
    level = 0 if ratio <= 0.8 else 1 if ratio <= 1.2 else 2 if ratio <= 1.6 else 3
    # 120일 넘게 걸리는 거래가 많거나, 한 번 밀리면 오래 밀리는 나라는 한 단계 올립니다.
    if (long_tail or 0) >= 10 or (late_days and bench_days and late_days >= bench_days * 1.3):
        level = min(level + 1, 3)
    return levels[level]


def _cautions(terms: dict, late, bench_late, late_prev, long_tail, days, bench_days) -> list[str]:
    """숫자에서 바로 나오는 주의점. 모든 문장에 근거 수치를 붙입니다."""

    notes = []
    oa, lc = terms.get("O/A(T/T 포함)"), terms.get("L/C")
    collection = sum(v for k, v in terms.items() if k in ("D/A", "D/P") and v)
    if oa is not None and oa >= 70:
        notes.append(f"거래의 {oa}%가 O/A(T/T 사후송금 포함) — 선적 후 대금을 받는 외상 거래가 "
                     "일반적입니다. 첫 거래는 선수금(T/T in advance) 비중을 높이거나 "
                     "단기수출보험으로 미회수 위험을 덮는 것이 안전합니다.")
    if lc is not None:
        if lc >= 10:
            notes.append(f"L/C 비중 {lc}% — 신용장 거래가 드물지 않아, 첫 거래에 L/C(일람불)를 "
                         "요구해도 무리한 요청이 아닙니다.")
        elif lc < 5:
            notes.append(f"L/C 비중 {lc}% — 현지에서 신용장이 드물어 L/C를 고집하면 협상이 "
                         "어려울 수 있습니다. 선수금 + 잔금 T/T 구조로 절충하는 경우가 많습니다.")
    if collection >= 5:
        notes.append(f"D/A·D/P(추심) 비중 {round(collection, 1)}% — 은행이 지급을 보증하지 않는 "
                     "방식이라, 서류 인도 조건과 인수 기한을 계약서에 분명히 적어야 합니다.")
    if late is not None and bench_late:
        if late > bench_late * 1.1:
            notes.append(f"연체율 {late}%로 전체 나라 평균({bench_late}%)보다 높습니다. 신용조사와 "
                         "결제 기한·지연이자 조항을 먼저 챙기세요.")
        elif late < bench_late * 0.9:
            notes.append(f"연체율 {late}%로 전체 나라 평균({bench_late}%)보다 낮은 편입니다.")
        else:
            notes.append(f"연체율 {late}%로 전체 나라 평균({bench_late}%)과 비슷합니다. 평균이어도 "
                         "다섯 건 중 한 건 가까이 늦게 들어온다는 뜻이니 결제 기한 조항은 챙기세요.")
    if late is not None and late_prev is not None and late - late_prev >= 2:
        notes.append(f"연체율이 {late_prev}% → {late}%로 오르는 추세입니다.")
    if long_tail is not None and long_tail >= 10:
        notes.append(f"결제에 120일 넘게 걸리는 거래가 {long_tail}%입니다. 자금 회전 계획에 넣어 두세요.")
    if days is not None and bench_days and days >= bench_days * 1.15:
        notes.append(f"평균 결제기간 {days}일로 전체 평균({bench_days}일)보다 깁니다.")
    return notes


def fetch_ksure_payment_risk(country_name: str = "") -> dict:
    """나라의 결제방식 비중, 평균 결제기간, 연체율, 참고 위험 등급과 주의점."""

    if not ksure_client.available():
        return _fail("무역보험공사 수출결제정보 키(DATA_GO_KR_SERVICE_KEY)가 없어 조회하지 "
                     "못했습니다.", "API_AUTH_FAILED")
    country = ksure_client.find_country(country_name)
    if not country:
        return _fail(f"'{country_name}'를 무역보험공사 나라 목록에서 찾지 못했습니다. "
                     "한글 정식 국가명(예: 베트남, 아랍에미리트 연합)으로 다시 불러 주세요.",
                     "VALIDATION_ERROR")
    result = ksure_client.payment_info(country["code"])
    if not result["success"]:
        return _fail(result.get("message") or "무역보험공사 결제 통계를 받지 못했습니다.",
                     result.get("error_code") or "API_ERROR")
    data = result["data"]
    bench = ksure_client.payment_info("")
    bench_data = bench["data"] if bench["success"] else None

    terms = _shares(data["payment_terms"])
    periods = _shares(data["payment_period"])
    term_map = {row["name"]: row["share_pct"] for row in terms}
    long_tail = next((row["share_pct"] for row in periods if row["code"].startswith("120_OVER")
                      or "초과" in row["name"]), None)
    late, late_prev = _value(data["late_payment_rate"]), _value(data["late_payment_rate"], 1)
    days, days_prev = _value(data["average_payment_days"]), _value(data["average_payment_days"], 1)
    late_days = _value(data["average_late_days"])
    bench_late = _value(bench_data["late_payment_rate"]) if bench_data else None
    bench_days = _value(bench_data["average_payment_days"]) if bench_data else None
    bench_late_days = _value(bench_data["average_late_days"]) if bench_data else None
    latest = _latest(data["late_payment_rate"]) or _latest(data["average_payment_days"])

    return {
        "success": True, "source": KSURE_SOURCE,
        "country": country["name"], "ksure_country_code": country["code"],
        "year": latest["year"] if latest else "",
        "last_update": data["last_update"],
        "payment_terms": sorted(terms, key=lambda row: -(row["share_pct"] or 0)),
        "payment_terms_note": ("결제방식 비중은 한국 수출기업이 무역보험을 이용한 거래의 건수 기준입니다. "
                               "T/T 사전송금은 별도 항목이 없고 O/A(T/T 포함)에 함께 집계됩니다."),
        "payment_period_distribution": periods,
        "average_payment_days": days, "prev_average_payment_days": days_prev,
        "late_payment_rate_pct": late, "prev_late_payment_rate_pct": late_prev,
        "average_late_days": late_days,
        "late_payment_trend": [{"year": row["year"], "pct": row["value"]}
                               for row in data["late_payment_rate"]],
        "benchmark_all_countries": {
            "late_payment_rate_pct": bench_late, "average_payment_days": bench_days,
            "average_late_days": bench_late_days,
        } if bench_data else None,
        "risk_level": _grade(late, bench_late, long_tail, late_days, bench_late_days),
        "risk_level_basis": RISK_BASIS,
        "cautions": _cautions(term_map, late, bench_late, late_prev, long_tail, days, bench_days),
    }


# --- OpenAI Function Calling -------------------------------------------------------

TOOLS = [
    {"type": "function", "function": {
        "name": "get_item_trade_statistics",
        "description": ("관세청 품목별 수출입실적(K-stat 품목별 표와 같은 자료)을 조회합니다. 품목(군) 아래 세부 품목마다 "
                        "순위, HS코드, 품목명, 전년 실적, 당해연도 수출액, 수출증감률(%), 무역수지를 천 달러(천불) "
                        "단위로 돌려줍니다. 품목·산업의 수출 실적, 수출액, 통계, 증감률을 물으면 반드시 부르세요. "
                        "(나라별 비교·수출국 추천은 fetch_customs_export_stats)"),
        "parameters": {"type": "object", "additionalProperties": False, "properties": {
            "item_name": {"type": "string", "description": "품목·산업의 짧은 한글 이름 (예: 의류, 화장품, 메모리, 반도체)"},
            "hs_code": {"type": "string", "description": ("품목의 HS부호 2·4·6자리. 확실할 때만 넣으세요 (예: 메모리 → \"8542\", "
                                                          "화장품 → \"3304\"). 모르면 비우세요.")},
            "period": {"type": "string", "enum": ["latest", "ytd"],
                       "description": "latest = 최근 완결 연도(기본), ytd = 올해 누계(자료가 있는 달까지, 전년 같은 기간 대비)"},
            "top": {"type": "integer", "description": "표에 넣을 품목 수 (기본 10, 최대 20)"},
        }, "required": ["item_name"]},
    }},
    {"type": "function", "function": {
        "name": "fetch_customs_export_stats",
        "description": ("관세청 품목별·국가별 수출입실적(GW)에서 한국의 품목 수출 실적을 조회합니다. "
                        "최근 연간(또는 올해 누적) 수출액, 전년 같은 기간 대비 증감률, 주요 수출국 순위와 "
                        "성장이 빠른 나라를 돌려줍니다. 수출 대상국 추천, 국가별 수출액 비교, "
                        "시장 규모 질문에 반드시 부르세요."),
        "parameters": {"type": "object", "additionalProperties": False, "properties": {
            "item_name": {"type": "string", "description": "사용자가 말한 품목의 짧은 한글 품명 (예: 의류, 립스틱, 라면)"},
            "target_year": {"type": "integer", "description": "조회할 해. 사용자가 말하지 않았으면 비우세요(최근 완결 연도를 씁니다). 올해를 주면 자료가 있는 달까지 누적합니다."},
            "hs_codes": {"type": "array", "items": {"type": "string"}, "maxItems": MAX_HS_CODES,
                         "description": ("품목에 해당하는 HS부호 2·4·6자리. 확실할 때만 넣으세요. 범위가 넓은 품목은 "
                                         "류(2자리)로 여러 개 줄 수 있습니다 (예: 의류 → [\"61\", \"62\"], 화장품 → [\"3304\"]). "
                                         "모르면 비우세요 — 품목표에서 품명으로 찾습니다.")},
            "top": {"type": "integer", "description": "돌려받을 상위 나라 수 (기본 5, 최대 10)"},
        }, "required": ["item_name"]},
    }},
    {"type": "function", "function": {
        "name": "fetch_ksure_payment_risk",
        "description": ("한국무역보험공사 수출결제정보에서 한 나라의 결제 동향을 조회합니다. 결제방식 비중"
                        "(O/A·T/T, L/C, D/A, D/P, CAD, COD), 평균 결제기간, 연체율과 추세, 전체 나라 평균과의 비교, "
                        "참고 위험 등급과 근거 수치가 붙은 주의점을 돌려줍니다. 결제조건·대금 회수 위험 질문, "
                        "수출 대상국 추천 시 후보 나라마다 부르세요."),
        "parameters": {"type": "object", "additionalProperties": False, "properties": {
            "country_name": {"type": "string", "description": "한글 국가명 (예: 미국, 베트남, 아랍에미리트 연합)"},
        }, "required": ["country_name"]},
    }},
]

HANDLERS = {
    "get_item_trade_statistics": get_item_trade_statistics,
    "fetch_customs_export_stats": fetch_customs_export_stats,
    "fetch_ksure_payment_risk": fetch_ksure_payment_risk,
}


def run_tool(name: str, arguments: dict) -> dict:
    """AI가 부른 도구를 실행합니다. 모르는 도구·인자는 거절하고, 어떤 오류도 밖으로 던지지 않습니다.

    도구가 실패해도 대화는 이어져야 합니다. 실패 이유를 돌려주면 AI가 "조회하지 못했다"고 말합니다.
    """

    handler = HANDLERS.get(name)
    if handler is None:
        return _fail(f"'{name}'는 없는 도구입니다.", "VALIDATION_ERROR")
    allowed = TOOLS[[tool["function"]["name"] for tool in TOOLS].index(name)]["function"]
    known = allowed["parameters"]["properties"]
    try:
        return handler(**{key: value for key, value in (arguments or {}).items() if key in known})
    except Exception:       # noqa: BLE001 — 외부 API 응답이 어떤 모양이든 대화는 이어갑니다.
        return _fail("데이터를 조회하는 중 오류가 났습니다. 잠시 뒤 다시 물어봐 주세요.", "API_ERROR")


def sources() -> list[dict]:
    """상담 화면이 '어떤 데이터로 답하는지' 보여 줄 때 씁니다."""

    return [trade_stats_client.sources(), ksure_client.sources()]
