"""관세청 수출입무역통계 (공공데이터포털).

"이 품목이 그 나라로 실제로 얼마나 나가고 있는가"를 봅니다. 처음 수출하는
사람이 가장 먼저 묻는 것이고, 시장이 있는지 없는지를 숫자로 알려 줍니다.

공공데이터포털 키(DATA_GO_KR_SERVICE_KEY) 하나로 여러 API를 쓰지만, API마다
따로 "활용신청"을 해야 열립니다. 신청하지 않은 API는 403을 냅니다. 그럴 때
어디서 신청하면 되는지 알려 줍니다.

    품목별: /1220000/Itemtrade/getItemtradeList   (HS부호 + 상대국)
    국가별: /1220000/nitemtrade/getNitemtradeList (HS부호, 나라를 가리지 않음)
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from datetime import date

from app.collectors import file_cache
from app.collectors.base_client import fail, get_config, ok, request_text

BASE = "https://apis.data.go.kr/1220000"
ITEM_URL = f"{BASE}/Itemtrade/getItemtradeList"
COUNTRY_URL = f"{BASE}/nitemtrade/getNitemtradeList"

# 같은 모양으로 답하는 관세청 무역통계들. 보는 각도만 다릅니다.
#   (이름, 주소, 더 넣어야 하는 값, 줄에서 이름이 되는 칸)
VIEWS = {
    "total": ("수출입총괄", f"{BASE}/Newtrade/getNewtradeList", {}, "year"),
    "continent": ("대륙별", f"{BASE}/continenttradet/getContinenttradeList", {},
                  "statCdCntnKor1"),
    "customs": ("세관별", f"{BASE}/customstrade/getCustomstradeList", {}, "center"),
    "port": ("항구·공항별", f"{BASE}/porttrade/getPorttradeList", {}, "statKor"),
    "kind": ("종류별", f"{BASE}/kindtrade/getKindtradeList", {"imexTpcd": "1"},
             "statCdCntnKor1"),
    "temper": ("성질별 국가별", f"{BASE}/ntempertrade/getNtempertradeList",
               {"imexTpcd": "1"}, "statCdCntnKor1"),
}

# 이 API를 쓰려면 아래에서 "활용신청"을 한 번 해야 합니다. (대개 즉시 승인)
SIGNUP = {
    "label": "공공데이터포털 · 관세청 수출입무역통계",
    "url": "https://www.data.go.kr/tcs/dss/selectDataSetList.do?keyword=수출입무역통계",
    "how": "검색 결과에서 '관세청_수출입무역통계'를 열고 [활용신청]을 누릅니다. "
           "같은 인증키로 바로 쓸 수 있습니다.",
}

NOT_SUBSCRIBED = ("SERVICE_KEY_IS_NOT_REGISTERED", "서비스키가 등록되지 않았습니다")


def available() -> bool:
    return bool(get_config("DATA_GO_KR_SERVICE_KEY", ""))


def _period(year: int | None = None) -> tuple[str, str]:
    """조회 기간. 관세청 통계는 해를 걸쳐 조회하면 한 건도 나오지 않습니다.

    그래서 한 해 단위로만 봅니다. 통계는 한두 달 늦게 올라오므로, 올해 자료가
    아직 없으면 지난해로 내려갑니다.
    """

    target = year or date.today().year
    return f"{target}01", f"{target}12"


def _call(url: str, params: dict, label: str) -> dict:
    key = get_config("DATA_GO_KR_SERVICE_KEY", "")
    if not key:
        return fail("API_AUTH_FAILED", "api",
                    f"{label} 키(DATA_GO_KR_SERVICE_KEY)가 없습니다.")

    result = request_text("GET", url, timeout=25,
                          params={"serviceKey": key, "type": "json", **params})
    if not result["success"]:
        # 활용신청을 하지 않으면 403이 옵니다. 키가 틀린 것과는 다릅니다.
        if result["error_code"] == "API_AUTH_FAILED":
            return fail("API_NOT_SUBSCRIBED", "api",
                        f"{label} API에 활용신청이 되어 있지 않습니다. "
                        f"{SIGNUP['how']}")
        return result

    text = result["data"]
    if any(mark in text for mark in NOT_SUBSCRIBED):
        return fail("API_NOT_SUBSCRIBED", "api",
                    f"{label} API에 활용신청이 되어 있지 않습니다. {SIGNUP['how']}")
    # type=json을 줘도 XML로 옵니다. 둘 다 읽을 수 있게 합니다.
    rows = _read_json(text)
    if rows is None:
        rows = _read_xml(text)
    if rows is None:
        return fail("API_INVALID_RESPONSE", "api")
    return ok(rows, "api")


def _read_json(text: str) -> list | None:
    try:
        body = json.loads(text)
    except ValueError:
        return None
    items = (body.get("response", {}).get("body", {}).get("items")
             or body.get("items") or [])
    if isinstance(items, dict):
        items = items.get("item") or []
    if isinstance(items, dict):
        items = [items]
    return items if isinstance(items, list) else []


def _read_xml(text: str) -> list | None:
    """<response><body><items><item>...</item></items></body></response>"""

    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return None
    code = (root.findtext(".//resultCode") or "").strip()
    if code and code != "00":
        return []
    return [{child.tag: (child.text or "").strip() for child in item}
            for item in root.iter("item")]


def _number(value) -> int:
    try:
        return int(str(value).replace(",", "").strip() or 0)
    except (TypeError, ValueError):
        return 0


def _row(raw: dict) -> dict:
    """관세청 응답 한 줄을 우리 모양으로.

    금액(expDlr·impDlr)은 **달러** 단위입니다. (2025년 HS 6109 총계가 271,743,781 —
    천 달러로 읽으면 티셔츠 수출이 2,700억 달러가 됩니다) 칸 이름의 _thousand는
    예전 이름이 남은 것이고 값은 달러입니다.
    """

    # 두 API가 칸 이름을 다르게 씁니다.
    #   품목별 국가별(Itemtrade): hsCode + statKor(품명)   ※ 나라는 요청에서 고정
    #   품목별(nitemtrade):      hsCd + statCd/statCdCntnKor1(나라) + statKor(품명)
    country = str(raw.get("statCdCntnKor1") or raw.get("cntyNm") or "").strip()
    return {
        "period": str(raw.get("year") or raw.get("yymm") or "").strip(),
        "hs_code": str(raw.get("hsCd") or raw.get("hsCode") or raw.get("hsSgn") or "").strip(),
        "product": str(raw.get("statKor") or "").strip(),
        "country": country,
        "country_code": str(raw.get("statCd") or raw.get("cntyCd") or "").strip(),
        "export_weight_kg": _number(raw.get("expWgt")),
        "export_usd_thousand": _number(raw.get("expDlr")),
        "import_weight_kg": _number(raw.get("impWgt")),
        "import_usd_thousand": _number(raw.get("impDlr")),
        "balance_usd_thousand": _number(raw.get("balPayments")),
    }


def item_trade(hs_code: str, country_code: str = "", year: int | None = None) -> dict:
    """HS부호(와 나라)로 실제 수출입 실적을 봅니다.

    올해 자료가 아직 없으면 지난해로 한 번 더 찾아봅니다.
    """

    digits = "".join(ch for ch in (hs_code or "") if ch.isdigit())
    if len(digits) < 4:
        return fail("VALIDATION_ERROR", "api", "HS부호를 4자리 이상 입력해주세요.")

    years = [year] if year else [date.today().year, date.today().year - 1]
    for attempt in years:
        start, end = _period(attempt)
        params = {"strtYymm": start, "endYymm": end, "hsSgn": digits[:10]}
        if country_code:
            params["cntyCd"] = country_code.strip().upper()[:2]

        result = _call(ITEM_URL if country_code else COUNTRY_URL, params, "수출입무역통계")
        if not result["success"]:
            return result
        if result["data"]:
            break

    rows = [_row(raw) for raw in result["data"] if isinstance(raw, dict)]
    # 합계 줄은 기간 칸이 "총계"로 오고 나라·부호가 "-"입니다.
    totals = [row for row in rows if row["period"] in ("총계", "합계")
              or row["country_code"] == "-"]
    rows = [row for row in rows if row not in totals]
    return ok({
        "hs_code": digits,
        "country_code": country_code.upper() if country_code else "",
        "from": start, "to": end,
        "rows": rows,
        "total": totals[0] if totals else None,
        "unit_note": "금액 단위는 달러(USD), 중량 단위는 kg입니다.",
    }, "api")


def top_destinations(hs_code: str, limit: int = 10, year: int | None = None) -> dict:
    """이 품목을 어느 나라로 가장 많이 내보내는지. 시장을 고를 때 씁니다.

    같은 나라가 달마다 여러 줄로 오므로 나라별로 더해서 순위를 냅니다.
    """

    result = item_trade(hs_code, year=year)
    if not result["success"]:
        return result

    by_country: dict[str, dict] = {}
    for row in result["data"]["rows"]:
        key = row["country_code"] or row["country"]
        if not key:
            continue
        found = by_country.setdefault(key, {
            "country": row["country"], "country_code": row["country_code"],
            "product": row["product"], "hs_code": row["hs_code"],
            "export_usd_thousand": 0, "export_weight_kg": 0,
            "import_usd_thousand": 0, "import_weight_kg": 0, "months": 0})
        for field in ("export_usd_thousand", "export_weight_kg",
                      "import_usd_thousand", "import_weight_kg"):
            found[field] += row[field]
        found["months"] += 1

    rows = sorted((row for row in by_country.values() if row["export_usd_thousand"] > 0),
                  key=lambda row: -row["export_usd_thousand"])[:max(1, limit)]
    return ok({**result["data"], "rows": rows,
               "note": f"{result['data']['from'][:4]}년에 실제로 신고된 수출 실적입니다."}, "api")


# 기간별 나라별 합계는 달이 끝나야 바뀝니다. 하루 동안은 받아 둔 것을 씁니다.
EXPORTS_CACHE_DAYS = 1


def exports_by_country(hs_code: str, start: str, end: str) -> dict:
    """정한 기간(YYYYMM~YYYYMM) 동안 이 품목의 나라별 수출액 합계. (금액은 달러)

    관세청 국가별 품목 통계(nitemtrade)는 달·나라·세부 부호마다 한 줄씩 옵니다.
    나라별로 더하고, 자료가 들어 있는 마지막 달(last_month, "2026.08")을 함께 돌려줍니다.
    올해처럼 아직 끝나지 않은 해를 지난해 같은 달까지와 견주려면 그 달이 필요합니다.
    HS부호는 2·4·6·10자리 모두 받습니다.

    같은 응답을 세부 부호(hsCd)별로도 더해 codes에 둡니다. 한 단계 아래 부호로 옵니다
    (2→4, 4→6, 6→10자리). K-stat의 품목별 수출입실적 표가 이것입니다.
    """

    digits = "".join(ch for ch in (hs_code or "") if ch.isdigit())[:10]
    if len(digits) < 2:
        return fail("VALIDATION_ERROR", "api", "HS부호를 2자리 이상 넣어 주세요.")
    # v2: codes·수입·무역수지를 함께 담습니다. 예전 모양의 파일은 쓰지 않습니다.
    cache_name = f"trade_exports_v2_{digits}_{start}_{end}"
    cached = file_cache.read(cache_name)
    if cached and cached[1] < EXPORTS_CACHE_DAYS:
        return ok(cached[0], "api")

    result = _call(COUNTRY_URL, {"strtYymm": start, "endYymm": end, "hsSgn": digits},
                   "수출입무역통계")
    if not result["success"]:
        return ok(cached[0], "cache") if cached else result

    countries: dict[str, dict] = {}
    codes: dict[str, dict] = {}
    total = None
    months: set[str] = set()
    for raw in result["data"]:
        if not isinstance(raw, dict):
            continue
        row = _row(raw)
        if row["period"] in ("총계", "합계") or row["country_code"] in ("-", ""):
            if row["period"] in ("총계", "합계"):
                total = row
            continue
        months.add(row["period"])
        found = countries.setdefault(row["country_code"], {
            "country": row["country"], "country_code": row["country_code"],
            "export_usd": 0, "export_weight_kg": 0})
        found["export_usd"] += row["export_usd_thousand"]
        found["export_weight_kg"] += row["export_weight_kg"]
        if row["hs_code"] and row["hs_code"] != "-":
            line = codes.setdefault(row["hs_code"], {
                "hs_code": row["hs_code"], "name": row["product"],
                "export_usd": 0, "import_usd": 0})
            line["export_usd"] += row["export_usd_thousand"]
            line["import_usd"] += row["import_usd_thousand"]

    export_sum = sum(row["export_usd"] for row in countries.values())
    import_sum = sum(row["import_usd"] for row in codes.values())
    data = {
        "hs_code": digits, "from": start, "to": end,
        "last_month": max(months) if months else "",
        "total_export_usd": total["export_usd_thousand"] if total else export_sum,
        "total_import_usd": total["import_usd_thousand"] if total else import_sum,
        "countries": countries,
        "codes": codes,
    }
    if countries:
        file_cache.write(cache_name, data)
    return ok(data, "api")


def sources() -> dict:
    """이 API를 지금 쓸 수 있는지. 화면에서 솔직하게 알립니다."""

    return {"key": "trade_stats", "label": "관세청 수출입무역통계",
            "env": "DATA_GO_KR_SERVICE_KEY", "ready": available(),
            "signup": SIGNUP}


def trade_view(view: str, year: int | None = None) -> dict:
    """무역통계를 다른 각도로 봅니다. (총괄 · 대륙별 · 세관별 · 항구별 · 종류별)

    모두 같은 모양으로 답하고, 조회 기간도 한 해 단위입니다.
    """

    if view not in VIEWS:
        return fail("VALIDATION_ERROR", "api", "볼 수 있는 통계가 아닙니다.")
    label, url, extra, name_field = VIEWS[view]

    years = [year] if year else [date.today().year, date.today().year - 1]
    for attempt in years:
        start, end = _period(attempt)
        result = _call(url, {"strtYymm": start, "endYymm": end, **extra}, label)
        if not result["success"]:
            return result
        if result["data"]:
            break

    rows = []
    for raw in result["data"]:
        if not isinstance(raw, dict):
            continue
        row = _row(raw)
        row["name"] = str(raw.get(name_field) or "").strip()
        row["export_count"] = _number(raw.get("expCnt"))
        row["import_count"] = _number(raw.get("impCnt"))
        # 종류별 통계만 칸 이름이 다릅니다. (dlr/wgt/cnt 한 벌로 옵니다)
        if raw.get("dlr") is not None and not row["export_usd_thousand"]:
            outgoing = str(raw.get("impexp") or "").strip() != "수입"
            amount, weight, count = (_number(raw.get("dlr")), _number(raw.get("wgt")),
                                     _number(raw.get("cnt")))
            if outgoing:
                row["export_usd_thousand"], row["export_weight_kg"] = amount, weight
                row["export_count"] = count
            else:
                row["import_usd_thousand"], row["import_weight_kg"] = amount, weight
                row["import_count"] = count
        rows.append(row)

    # 이름 없이 오는 줄(합계·미상)은 빼고 봅니다.
    rows = [row for row in rows if row["name"] not in ("-", "")]

    # 달마다 나뉘어 오므로 이름별로 더해 한 줄씩 만듭니다.
    merged: dict[str, dict] = {}
    for row in rows:
        key = row["name"] or row["period"]
        found = merged.setdefault(key, {
            "name": key, "export_usd_thousand": 0, "export_weight_kg": 0,
            "import_usd_thousand": 0, "import_weight_kg": 0,
            "export_count": 0, "import_count": 0, "months": 0})
        for field in ("export_usd_thousand", "export_weight_kg", "import_usd_thousand",
                      "import_weight_kg", "export_count", "import_count"):
            found[field] += row[field]
        found["months"] += 1

    ordered = sorted(merged.values(), key=lambda row: -row["export_usd_thousand"])
    return ok({
        "view": view, "label": label, "from": start, "to": end, "rows": ordered,
        "note": f"{start[:4]}년 {label} 실적입니다. 금액 단위는 달러(USD)입니다.",
    }, "api")
