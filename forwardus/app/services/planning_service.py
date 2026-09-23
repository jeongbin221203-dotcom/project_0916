"""Shipment planning: locations, cargo, schedules, shipment creation."""

from __future__ import annotations

import re
from datetime import date

from app.collectors import (customs_client, exchange_client, location_client, schedule_client,
                            tariff_client)
from app.collectors.base_client import load_mock
from app.models import Cargo, Shipment
from app.processors.cargo_calculator import calculate_cargo_lines, calculate_cargo_metrics
from app.processors.cost_calculator import INCOTERMS_FLOW_STEPS, INCOTERMS_INFO, calculate_logistics_cost
from app.processors import dangerous_goods, fta_guide, korean
from app.processors import transit_calculator
from app.processors.transit_calculator import great_circle_km
from app.processors.schedule_calculator import (
    DEFAULT_TRANSIT_DAYS,
    calculate_eta,
    calculate_cargo_ready_date,
    check_buyer_deadline,
    check_departure_margin,
)
from app.repositories import buyer_repository, shipment_repository
from app.services import ServiceError
from app.validators import ValidationError
from app.validators.cargo_validator import PACKAGE_TYPE_INFO, PACKAGE_TYPES, PACKING_GROUPS
from app.validators.shipment_validator import (
    optional_text,
    parse_date,
    validate_net_weight,
    validate_parties,
    validate_route,
    validate_trade_terms,
)

SORT_OPTIONS = {"recommended": "추천순", "price": "최저 운임순", "duration": "최단 운송기간순"}

# 한국 교역액 상위 국가 (관세청·무역협회 교역 규모 기준). 도착지 국가 목록 상단에
# "주요 무역국"으로 먼저 노출합니다.
TOP_TRADE_PARTNERS = [
    "CN", "US", "VN", "JP", "HK", "TW", "SG", "IN", "MX", "AU",
    "MY", "ID", "PH", "DE", "TH", "PL", "NL", "SA", "CA", "AE",
]


def location_kind(transport_mode: str) -> str:
    return "airport" if transport_mode == "AIR" else "port"


def get_form_options() -> dict:
    """Static options the planning form needs on first render."""

    return {
        "incoterms": INCOTERMS_INFO,
        "incoterm_flow": INCOTERMS_FLOW_STEPS,
        "package_types": PACKAGE_TYPE_INFO,
        "sort_options": SORT_OPTIONS,
        # 고르는 칸이라 바깥을 부르지 않습니다. 환율은 exchange_rates()로 따로 받습니다.
        "currencies": exchange_client.currency_options(),
        "dg_classes": dangerous_goods.classes(),
        "packing_groups": PACKING_GROUPS,
    }


def un_number_search(query: str) -> dict:
    """UN번호를 물품 이름·영문 품명·번호로 찾습니다. 찾는 방법 안내도 함께 줍니다."""

    return {"items": dangerous_goods.search_un_numbers(query),
            **dangerous_goods.lookup_help()}


def dangerous_goods_guide(dg_class: str, transport_mode: str, country_code: str = "") -> dict:
    """고른 위험물 등급을 어떻게 보내야 하는지 정리합니다."""

    country = (country_code or "").strip().upper()
    location = location_client.find_location(country) if len(country) > 2 else None
    if location:
        country = location["country_code"]
    country_name = location_client.country_name(country) if country else ""
    # 도착국별 위험물 반입 기준을 모아 둔 공개 자료는 없습니다. 잘못된 곳을 가리키느니
    # 규정 원문(IMDG·IATA)과 "선사·항공사에 확인" 안내만 둡니다.
    return dangerous_goods.guide(dg_class, transport_mode, country_name or "")


def search_locations(query: str, transport_mode: str, role: str | None = None, country: str | None = None,
                     origin_code: str | None = None) -> dict:
    """Search ports or airports. Export flow: origin in Korea, destination abroad."""

    if role == "origin":
        country = "KR"
        origin_code = None
    result = location_client.search_locations(query, location_kind(transport_mode.upper()), country, origin_code)
    if not result["success"]:
        return result
    if role == "destination":
        result["data"] = [item for item in result["data"] if item["country_code"] != "KR"]
    if role == "origin" and not query.strip():
        # 목록을 펼치면 국가관리 무역항만 보여줍니다. 지방관리 무역항은
        # 이름을 입력하면 찾을 수 있습니다. (수출 물량 대부분이 국가관리항입니다)
        result["data"] = [item for item in result["data"]
                          if item["kind"] == "airport" or item["port_class"] != "local"]
    return result


def related_locations(code: str, transport_mode: str, role: str | None = None) -> dict:
    """고른 곳과 같은 나라의 항구·공항을, 관련도 높은 순서로 돌려줍니다.

    서류에서 읽은 항구가 늘 맞지는 않습니다(같은 나라에 항구가 여럿입니다).
    그래서 ▼를 누르면 그 나라의 다른 곳을 바로 고를 수 있게 합니다.
    고른 곳이 맨 앞에 오고, 나머지는 물동량·항만 등급 순서 그대로입니다.
    """

    info = location_client.find_location(code)
    if not info:
        return search_locations("", transport_mode, role)
    result = search_locations("", transport_mode, role, country=info.get("country_code"))
    if not result["success"]:
        return result
    rows = [item for item in result["data"] if item["code"] != info["code"]]
    chosen = next((item for item in result["data"] if item["code"] == info["code"]), info)
    result["data"] = [chosen, *rows]
    return result


def list_countries(transport_mode: str, role: str | None = None) -> dict:
    """Destination country list, with Korea's main trading partners ranked first."""

    result = location_client.list_countries(
        location_kind(transport_mode.upper()), exclude=["KR"] if role == "destination" else None
    )
    if result["success"]:
        ranks = {code: index + 1 for index, code in enumerate(TOP_TRADE_PARTNERS)}
        for country in result["data"]:
            country["trade_rank"] = ranks.get(country["code"])
    return result


def search_unlocode(query: str, role: str | None = None, country: str | None = None,
                    transport_mode: str = "SEA") -> dict:
    """직접 입력 칸의 후보 목록.

    항공은 공항 목록에서, 해상은 UN/LOCODE 전체 항구 색인에서 찾습니다.
    출발지는 국내(KR)로 한정합니다.
    """

    country = "KR" if role == "origin" else country
    if transport_mode.upper() == "AIR":
        result = location_client.search_locations(query, "airport", country)
        if result["success"] and role == "destination":
            result["data"] = [item for item in result["data"] if item["country_code"] != "KR"]
        return result
    return location_client.search_unlocode(country, query)


# 관세청 HS부호검색은 관세율표에 적힌 한글 품명으로만 찾습니다.
# 영문이나 오타로 적으면 한 건도 안 나옵니다. 그래서 못 찾으면 AI에게
# "관세율표에서는 이 물건을 뭐라고 부르나"를 물어 그 낱말로 다시 찾습니다.
HS_HINT_PROMPT = """사용자가 수출할 물건의 이름을 적었습니다.
한국 관세율표(HS)에서 그 물건을 가리키는 한국어 품명 후보를 최대 3개 고르세요.

규칙
- 관세율표에 실제로 쓰이는 낱말로만 답하세요. (예: 치약, 샴푸, 화장비누, 가죽제 가방)
- 영문이나 오타로 적혀 있어도 무슨 물건인지 알아내세요. (toothpaste, tooth paist -> 치약)
- 상표명이나 광고 문구는 빼고 물건 자체의 이름만 남기세요.
- 무슨 물건인지 알 수 없으면 빈 목록을 주세요. 지어내지 마세요.

JSON만 답하세요: {"names": ["치약"]}"""


def _hs_name_hints(query: str) -> list[str]:
    """영문·오타로 적힌 품명을 관세율표 한글 품명으로 바꿔 봅니다."""

    import json

    from app.collectors import ai_client

    if not ai_client.available():
        return []
    result = ai_client.chat([
        {"role": "system", "content": HS_HINT_PROMPT},
        {"role": "user", "content": query[:200]},
    ], max_tokens=120)
    if not result["success"]:
        return []
    try:
        names = json.loads(result["data"]).get("names") or []
    except ValueError:
        return []
    return [str(name).strip()[:40] for name in names[:3] if str(name).strip()]


def search_hs_codes(query: str, *, compare_navigation: bool = False,
                    country: str = "", order: str = "frequency") -> dict:
    """관세청 HS부호검색. 못 찾으면 품명을 바꿔 한 번 더 찾습니다.

    관세청이 멈추면 무료 국제 출처(UN·미국·영국)로 6자리라도 찾아 줍니다.
    6자리는 신고에 그대로 쓸 수 없으므로 그렇다고 밝힙니다.

    compare_navigation=True(화면 검색)이면 AI 품명 해석 → 후보 적합도 →
    품목란 건수·도착국 관세 비교까지 한 뒤 우선순위로 정렬해 돌려줍니다.
    """

    if compare_navigation:
        from app.services import hs_suggestion_service
        return hs_suggestion_service.search(query, country, order)

    text = (query or "").strip()
    found = customs_client.search_hs_codes(text)

    # 관세청이 실데이터를 줬으면 그대로 씁니다.
    if found["success"] and found["data"] and found["source"] == "api":
        return found
    if not text:
        return found

    if found["success"] and not found["data"]:
        for name in _hs_name_hints(text):
            if name == text:
                continue
            retry = customs_client.search_hs_codes(name)
            if retry["success"] and retry["data"]:
                # 무슨 낱말로 바꿔 찾았는지 화면에서 밝혀 줍니다.
                return {**retry, "searched_as": name, "original_query": text}

    # 관세청이 답하지 않거나 예시로 대체됐으면 국제 출처를 봅니다.
    fallback = _hs_from_open_sources(text)
    return fallback if fallback else found


def _hs_from_open_sources(query: str) -> dict | None:
    """무료 국제 출처에서 HS 6자리를 찾습니다. (키가 필요 없습니다)

    관세청은 한글 품명으로만 찾고, 이쪽은 영문으로만 찾습니다. 그래서 한글로
    적었으면 먼저 영문 품명으로 바꿔 봅니다.
    """

    from app.collectors import hs_open_client

    candidates = [query]
    if any("가" <= ch <= "힣" for ch in query):
        candidates = _hs_english_hints(query) + candidates

    for text in candidates:
        result = hs_open_client.search(text, limit=10)
        if not result["success"] or not result["data"]["rows"]:
            continue
        rows = [{
            "code": row["hs6"],
            "name": row["names"][0] if row["names"] else "",
            "name_en": row["names"][0] if row["names"] else "",
            "quantity_unit": "", "weight_unit": "",
            "partial": True,                 # 6자리라 신고에 그대로 못 씁니다.
            "from": " · ".join(row["sources"]),
        } for row in result["data"]["rows"]]
        return {
            "success": True, "source": "open", "data": rows,
            "searched_as": text if text != query else "",
            "original_query": query,
            "partial_note": result["data"]["limit_note"],
        }
    return None


HS_ENGLISH_PROMPT = """사용자가 수출할 물건의 이름을 한국어로 적었습니다.
국제 HS 품목분류(영문)에서 그 물건을 찾을 때 쓸 영어 낱말을 최대 3개 고르세요.

규칙
- 관세율표에서 쓰는 일반 명사로만 답하세요. (치약 -> toothpaste, 가죽가방 -> leather bag)
- 상표명은 빼고 물건 자체의 이름만 남기세요.
- 무슨 물건인지 알 수 없으면 빈 목록을 주세요. 지어내지 마세요.

JSON만 답하세요: {"words": ["toothpaste"]}"""


def _hs_english_hints(query: str) -> list[str]:
    """한글 품명을 국제 분류에서 찾을 영어 낱말로 바꿉니다."""

    import json

    from app.collectors import ai_client

    if not ai_client.available():
        return []
    result = ai_client.chat([
        {"role": "system", "content": HS_ENGLISH_PROMPT},
        {"role": "user", "content": query[:200]},
    ], max_tokens=100)
    if not result["success"]:
        return []
    try:
        words = json.loads(result["data"]).get("words") or []
    except ValueError:
        return []
    return [str(word).strip()[:40] for word in words[:3] if str(word).strip()]


def exchange_rates() -> dict:
    """통화별 원화 환율. 관세청 고시 환율을 씁니다.

    화면에 "무슨 환율로 얼마에 환산했는지"를 함께 보여주려고 기준일과 출처
    문구를 같이 돌려줍니다.
    """

    result = exchange_client.fetch_krw_rates()
    applied = result.get("applied_date") or ""
    live = result["source"] == "api"
    return {
        "success": result["success"],
        "data": result["data"],
        "source": result["source"],
        "applied_date": applied,
        "basis": (f"관세청 고시환율{f' · {applied} 적용' if applied else ''}" if live
                  else "고시환율을 받지 못해 임시 환율로 환산했습니다"),
    }


def tariff_summaries(hs_codes: list[str], country_code: str) -> dict:
    """HS 후보 여러 개에 대해 "도착국에 쓸 수 있는 협정"을 한 줄씩 요약합니다.

    HS 검색 목록에서 어느 부호를 고를지 판단하는 데 씁니다. 후보마다 관세청을
    한 번씩 불러야 하므로 동시에 조회합니다.
    """

    from concurrent.futures import ThreadPoolExecutor

    codes = [code for code in dict.fromkeys(hs_codes) if code][:MAX_TARIFF_SUMMARIES]
    if not codes or not country_code:
        return {}

    def summarize(code: str) -> tuple[str, dict]:
        guide = tariff_guide(code, country_code)
        if not guide.get("available"):
            return code, {"status": "unknown", "text": "세율 정보 없음"}
        if guide["agreements"]:
            best = guide["agreements"][0]
            others = len(guide["agreements"]) - 1
            text = f"{best['agreement']} {best['rate']}%" + (f" 외 {others}건" if others else "")
            return code, {"status": "agreement", "text": text, "rate": best["rate"],
                          "agreement": best["agreement"]}
        base = next((row for row in guide["general"] if row["code"] == "A"), None)
        text = f"협정 없음 · 기본세율 {base['rate']}%" if base else "협정 없음"
        return code, {"status": "none", "text": text}

    with ThreadPoolExecutor(max_workers=6) as pool:
        return dict(pool.map(summarize, codes))


def tariff_guide(hs_code: str, country_code: str) -> dict:
    """고른 품목과 도착국에 맞는 협정·세율을 정리합니다.

    협정과 대상국은 관세청 관세율구분명에서 읽어내고, 나라 이름은 관세청
    국가코드 목록과 맞춥니다. 세율은 한국으로 수입할 때 기준이라 참고값으로
    보여주고, 앞에는 "쓸 수 있는 협정과 필요한 원산지증명"을 둡니다.
    """

    country = (country_code or "").strip().upper()
    location = location_client.find_location(country) if len(country) > 2 else None
    if location:
        country = location["country_code"]
    country_name = location_client.country_name(country) or country

    result = customs_client.fetch_tariff_rates(hs_code)
    if not result["success"]:
        return {"available": False, "message": result["message"], "country": country_name}

    codes = customs_client.fetch_country_codes()
    country_codes = codes["data"] if codes["success"] else {}
    # {코드: 한글 국가명} — 여러 나라가 묶인 협정을 설명할 때 씁니다.
    by_code = {iso: name for name, iso in country_codes.items()}

    matched, general = [], []
    for row in result["data"]:
        if row["code"] in fta_guide.GENERAL_RATES:
            general.append({**row, "description": fta_guide.GENERAL_RATES[row["code"]]})
            continue
        countries = fta_guide.countries_for(row["code"], row["name"], country_codes)
        if country in countries:
            matched.append({**row,
                            "agreement": fta_guide.agreement_label(row["name"]),
                            "about": fta_guide.describe(row["code"], row["name"], countries, by_code),
                            "certificate": fta_guide.certificate_for(row["code"], row["name"]),
                            "steps": fta_guide.certificate_steps(
                                fta_guide.certificate_for(row["code"], row["name"])),
                            "proof": fta_guide.proof_for(row["code"], row["name"])})

    # 같은 협정에서 선택1·선택2가 함께 오면 세율이 낮은 쪽만 남깁니다.
    best: dict[str, dict] = {}
    for row in matched:
        current = best.get(row["agreement"])
        if not current or _rate_value(row["rate"]) < _rate_value(current["rate"]):
            best[row["agreement"]] = row

    digits = hs_code.replace(".", "").replace("-", "").replace(" ", "")
    return {
        "available": True,
        "hs_code": customs_client.format_hs_code(digits),
        # HS 앞 6자리는 세계 공통(WCO)이고, 뒤 4자리는 나라마다 다릅니다.
        "hs6": f"{digits[:4]}.{digits[4:6]}" if len(digits) >= 6 else "",
        "hs6_note": (f"앞 6자리 {digits[:4]}.{digits[4:6]}까지는 세계 공통입니다."
                     f" 뒤 4자리는 나라마다 달라, {country_name}에서 쓰는 전체 부호는"
                     f" 그 나라 관세율표에서 확인해야 합니다.") if len(digits) >= 6 else "",
        "country": country_name,
        "country_code": country,
        "agreements": sorted(best.values(), key=lambda row: _rate_value(row["rate"])),
        "general": general,
        "note": "세율은 한국으로 수입할 때 기준입니다. 도착국이 매기는 관세는 그 나라가 정합니다.",
        "source": "api",
    }


def _rate_value(rate: str) -> float:
    try:
        return float(rate)
    except (TypeError, ValueError):
        return 999.0


# 나라별 세분 부호를 API로 받을 수 있는 곳. 그 밖의 나라는 WITS의 HS 6단위 세율과
# 공식 조회 페이지 링크로 안내합니다.
NATIONAL_TARIFF_SYSTEMS = {
    "US": {"label": "미국 HTS(USITC) 세분 부호", "digits": "10자리",
           "columns": [("general", "일반세율"), ("korea", "한국산(KR)")]},
    "GB": {"label": "영국 Trade Tariff 세분 부호", "digits": "10자리",
           "columns": [("general", "제3국 세율"), ("korea", "한국산 특혜")]},
    "JP": {"label": "일본 실행관세율표 통계부호", "digits": "9자리",
           "columns": [("general", "기본세율"), ("wto", "WTO세율"), ("korea", "한국산(RCEP)")]},
}
WITS_RATE_NOTE = ("세계은행 WITS(UNCTAD TRAINS)가 모은 각국 신고 세율입니다."
                  " HS 6자리 아래 세분 부호가 여러 개면 그 평균이라 최소·최대를 함께 적었습니다.")


def destination_tariff(hs_code: str, country_code: str) -> dict:
    """도착국이 실제로 매기는 관세와 그 나라의 세분 부호를 정리합니다.

    HS 앞 6자리는 세계 공통이라 WITS에서 모든 나라의 6단위 세율(MFN·한국산 특혜)을
    받고, 세분 부호(뒤 자리)는 API가 있는 미국·영국·일본만 그 나라 관세율표에서
    가져옵니다. EU 등 나머지는 공식 조회 페이지 링크를 붙입니다.
    """

    from concurrent.futures import ThreadPoolExecutor

    country = (country_code or "").strip().upper()
    location = location_client.find_location(country) if len(country) > 2 else None
    if location:
        country = location["country_code"]
    digits = "".join(ch for ch in (hs_code or "") if ch.isdigit())
    if len(digits) < 6 or not country:
        return {"available": False, "message": "HS 6자리 이상과 도착국이 필요합니다."}

    hs6 = digits[:6]
    eu_members = fta_guide.blocs().get("EU", ())
    reporter = tariff_client.reporter_for(country, eu_members)
    country_name = location_client.country_name(country) or country

    with ThreadPoolExecutor(max_workers=3) as pool:
        mfn = pool.submit(tariff_client.fetch_wits, reporter, tariff_client.WORLD, hs6)
        korea = pool.submit(tariff_client.fetch_wits, reporter, tariff_client.KOREA, hs6)
        national = pool.submit(_national_tariff_lines, country, hs6)
        mfn, korea, national = mfn.result(), korea.result(), national.result()

    mfn_row = mfn.get("data") if mfn["success"] else None
    pref_row = korea.get("data") if korea["success"] else None

    rates = []
    if mfn_row:
        rates.append({"label": "MFN(최혜국) 세율", **mfn_row})
    if pref_row:
        rates.append({"label": "한국산 특혜세율", **pref_row})
    elif mfn_row:
        # 특혜 자료가 없는 이유는 둘 중 하나입니다. MFN이 이미 0%면 특혜를 따로 둘 이유가 없습니다.
        rates.append({"label": "한국산 특혜세율", "rate": None,
                      "note": ("MFN 세율이 0%라 한국산에 따로 깎아 줄 세율이 없습니다." if mfn_row["rate"] == 0 else
                               "이 자료에는 한국산 특혜세율이 없습니다."
                               " 협정이 없거나 아직 반영되지 않았을 수 있어 아래 관세율표에서 확인하세요.")})

    return {
        # 세율을 못 받아도 공식 관세율표 링크는 늘 안내합니다.
        "available": True,
        "country": country_name,
        "country_code": country,
        "hs6": f"{hs6[:4]}.{hs6[4:]}",
        "in_eu": country in eu_members,
        "rates": rates,
        "advice": _tariff_advice(mfn_row, pref_row, country_name),
        "rate_note": WITS_RATE_NOTE if rates else
                     f"{country_name}의 이 품목 세율 자료가 없습니다. 아래 관세율표에서 직접 확인하세요.",
        "national": national,
        "national_note": (
            f"뒤 자리는 나라마다 달라 우리 부호 {customs_client.format_hs_code(digits)}와 1:1로"
            f" 맞지 않습니다. 품목 설명이 맞는 줄을 고르세요."
            if national else
            f"{korean.josa(country_name, '이')} 쓰는 세분 부호와 확정 세율은"
            f" 아래 공식 관세율표에서 확인합니다."),
        "link": tariff_client.lookup_page(country, hs6, eu_members),
        "source": "api",
    }


def _tariff_advice(mfn: dict | None, pref: dict | None, country_name: str) -> dict | None:
    """협정을 쓰는 게 유리한지 한 줄로 알려줍니다.

    FTA 특혜세율은 "쓸 수 있는 선택지"이지 의무가 아닙니다. 단계적 철폐 중이라
    특혜세율이 MFN보다 높은 구간도 실제로 있어(예: 한ㆍ중 FTA 일부 품목),
    그럴 때는 원산지증명서 없이 MFN으로 보내는 편이 쌉니다.
    """

    if not mfn or not pref or pref.get("rate") is None:
        return None
    gap = round(mfn["rate"] - pref["rate"], 2)
    if gap > 0:
        return {"kind": "use_fta",
                "text": f"협정을 쓰면 {gap}%p 낮습니다. 원산지증명서를 갖추면 {pref['rate']}%로 통관합니다."}
    if gap < 0:
        return {"kind": "use_mfn",
                "text": f"한국산 특혜세율({pref['rate']}%)이 MFN({mfn['rate']}%)보다 높습니다."
                        f" 특혜세율은 의무가 아니므로 원산지증명서 없이 MFN으로 보내는 편이 쌉니다."
                        f" 관세 철폐가 진행 중인 품목일 수 있어 {country_name} 관세율표에서 올해 세율을 확인하세요."}
    return {"kind": "same",
            "text": f"협정을 써도 세율이 {mfn['rate']}%로 같습니다. 원산지증명서를 준비할 실익이 없습니다."}


def _national_tariff_lines(country: str, hs6: str) -> dict | None:
    """미국·영국·일본의 세분 부호 목록. 다른 나라는 None."""

    system = NATIONAL_TARIFF_SYSTEMS.get(country)
    if not system:
        return None

    if country == "US":
        result = tariff_client.fetch_us_hts(hs6[:4])
        lines = _us_lines_under(result["data"], hs6) if result["success"] else []
        edition = ""
    elif country == "GB":
        result = tariff_client.fetch_uk_heading(hs6[:4])
        lines = _uk_lines_under(result["data"], hs6) if result["success"] else []
        edition = ""
    else:
        result = tariff_client.fetch_japan_tariff(hs6)
        lines = [{"code": row["code"], "description": row["description"], "indent": 1 if row["stat"] else 0,
                  "general": row["general"] or row["temporary"], "wto": row["wto"], "korea": row["korea"]}
                 for row in result["data"]["lines"] if row["hs"].replace(".", "") != hs6[:4]] if result["success"] else []
        edition = result["data"]["edition"] if result["success"] else ""

    if not lines:
        return None
    keys = [key for key, _ in system["columns"]]
    return {"label": system["label"], "digits": system["digits"], "edition": edition,
            "columns": [{"key": key, "label": label} for key, label in system["columns"]],
            "lines": _inherit_rates(lines, keys)}


def _inherit_rates(lines: list[dict], keys: list[str]) -> list[dict]:
    """세율은 상위 줄에만 적히고 통계용 하위 줄은 비어 있습니다. 가까운 상위 줄 값을 물려줍니다."""

    parents: list[dict] = []          # 들여쓰기 단계별로 가장 가까운 상위 줄
    for line in lines:
        indent = line.get("indent", 0)
        del parents[indent:]
        for key in keys:
            if not line.get(key):
                line[key] = next((p[key] for p in reversed(parents) if p.get(key)), "")
        parents.append(line)
    return lines


def _us_lines_under(rows: list[dict], hs6: str) -> list[dict]:
    """HTS 목록에서 HS 6자리 아래의 부호가 있는 줄만 남깁니다. ("Other:" 같은 소제목 줄은 뺍니다.)"""

    lines = []
    for row in rows:
        code = row["code"].replace(".", "")
        if not (code.startswith(hs6) and len(code) > 6):
            continue
        lines.append({"code": row["code"], "description": row["description"], "indent": row["indent"],
                      "general": row["general"], "korea": _us_korea_rate(row["special"], row["general"])})
    return lines


def _us_korea_rate(special: str, general: str) -> str:
    """HTS 특별세율 난("Free (A, AU, KR, ...)")에서 한국(KR)에 적용되는 세율만 뽑습니다."""

    for rate, members in re.findall(r"([^()]+?)\s*\(([^)]*)\)", special or ""):
        if "KR" in [m.strip() for m in members.split(",")]:
            return rate.strip()
    return ""


def _uk_lines_under(rows: list[dict], hs6: str) -> list[dict]:
    """영국 헤딩 목록에서 HS 6자리 아래 줄을 고르고, 잎 줄마다 한국산 특혜세율을 받습니다."""

    from concurrent.futures import ThreadPoolExecutor

    picked = [row for row in rows if row["code"].startswith(hs6)]

    def korea_rate(row: dict) -> str:
        if not row["leaf"]:
            return ""
        result = tariff_client.fetch_uk_tariff(row["code"])
        if not result["success"]:
            return ""
        return next((m["rate"] for m in result["data"]["measures"]
                     if m["type"] == "Tariff preference" and m["area"] == "KR"), "")

    with ThreadPoolExecutor(max_workers=4) as pool:
        korea = list(pool.map(korea_rate, picked))
    return [{"code": f"{row['code'][:4]}.{row['code'][4:6]}.{row['code'][6:]}", "description": row["description"],
             "indent": row["indent"], "general": row["general"], "korea": rate}
            for row, rate in zip(picked, korea)]


def _resolve_location(payload: dict, role: str, kind: str) -> dict:
    """Return a location from the master list, or build one from direct input.

    Direct input is kept because UN/LOCODE does not cover every terminal a
    forwarder may quote. Such a location is marked ``source = manual``.
    """

    field = f"{role}_code"
    code = str(payload.get(field) or "").strip().upper()
    custom = payload.get(f"{role}_custom") or {}
    known = location_client.find_location(code)

    if known and known["kind"] == kind:
        location = known
    elif custom:
        location = _build_custom_location(code, custom, role, kind)
    elif known:
        raise ValidationError(
            f"{code}은(는) {'공항' if kind == 'airport' else '항구'} 코드가 아닙니다.", field)
    else:
        raise ValidationError("목록에서 선택하거나 직접 입력해주세요.", field)


    if role == "origin" and location["country_code"] != "KR":
        raise ValidationError("수출 견적은 국내 항구·공항에서 출발합니다.", field)
    if role == "destination" and location["country_code"] == "KR":
        raise ValidationError("도착지는 해외 항구·공항이어야 합니다.", field)
    return location


def _build_custom_location(code: str, custom: dict, role: str, kind: str) -> dict:
    """직접 입력한 항구·공항. 코드를 비우면 이름으로 임시 코드를 부여합니다."""

    field = f"{role}_code"
    country_code = "KR" if role == "origin" else str(custom.get("country_code") or "").strip().upper()
    country = location_client.get_country(country_code)
    if not country:
        raise ValidationError("국가를 선택해주세요.", f"{role}_country")

    name = optional_text(custom.get("name"), max_length=200)
    if not name:
        raise ValidationError("항구·공항 이름을 입력해주세요.", f"{role}_name")

    if kind == "airport":
        return _build_custom_airport(code, name, country_code, country)

    # 서류에 찍히는 코드이므로 실제 UN/LOCODE만 사용합니다.
    if code:
        official = location_client.lookup_unlocode(code)
        if not official:
            raise ValidationError(f"{code}은(는) UN/LOCODE에 없는 코드입니다. 항구 이름으로 다시 찾아주세요.", field)
        if official["country_code"] != country_code:
            raise ValidationError(
                f"{code}은(는) {official['country_code']} 국가의 코드입니다. 국가를 확인해주세요.", f"{role}_country")
    else:
        matches = location_client.find_unlocode_by_name(country_code, name)
        if not matches:
            raise ValidationError(
                f"'{name}'을(를) UN/LOCODE에서 찾지 못했습니다. 항구 이름을 영문으로 입력하거나 코드를 입력해주세요.",
                f"{role}_name")
        if len(matches) > 1 and matches[0]["name_en"].lower() != name.strip().lower():
            candidates = ", ".join(f"{item['name_en']}({item['code']})" for item in matches)
            raise ValidationError(f"항구가 여러 곳 검색되었습니다. 코드를 선택해 입력해주세요: {candidates}", field)
        code = matches[0]["code"]
        official = matches[0]

    return {
        "code": code,
        "name": name,
        "name_en": official["name_en"],
        "city": name,
        "city_en": official["name_en"],
        "country": country["name"],
        "country_en": country["name_en"],
        "country_code": country_code,
        "region": country["region"],
        "kind": kind,
        "major": False,
        "source": "manual",
    }


def _build_custom_airport(code: str, name: str, country_code: str, country: dict) -> dict:
    """직접 입력한 공항. IATA 코드 또는 이름으로 실제 공항을 찾습니다."""

    known = location_client.find_location(code) if code else None
    if not known:
        matches = [item for item in location_client.search_locations(name, "airport", country_code)["data"]]
        if not matches:
            raise ValidationError(
                f"'{name}'에 해당하는 공항을 찾지 못했습니다. 공항 이름이나 IATA 코드(예: ICN)를 확인해주세요.",
                "origin_name" if country_code == "KR" else "destination_name")
        known = matches[0]

    if known["kind"] != "airport":
        raise ValidationError(f"{known['code']}은(는) 공항 코드가 아닙니다.", "destination_code")
    if known["country_code"] != country_code:
        raise ValidationError(
            f"{known['code']}은(는) {known['country']} 공항입니다. 국가를 확인해주세요.", "destination_country")
    return known


def _resolve_locations(route: dict, payload: dict) -> tuple[dict, dict]:
    kind = location_kind(route["transport_mode"])
    return _resolve_location(payload, "origin", kind), _resolve_location(payload, "destination", kind)


def calculate_cargo(payload: dict) -> dict:
    """화물 계산. 품목 하나만 보내던 예전 방식과 여러 품목 모두 받습니다.

    입력하는 도중에 부르는 화면용 계산이라 위험물 칸이 덜 채워졌다고 막지
    않습니다. CBM·중량은 치수와 수량만 있으면 낼 수 있기 때문입니다.
    덜 채운 항목은 `dg_warnings`로 돌려주고, 저장할 때 다시 확인합니다.
    """

    if isinstance(payload, dict) and (payload.get("cargo") or payload.get("items")):
        return calculate_cargo_lines(cargo_items(
            payload if payload.get("cargo") else {"cargo": payload.get("items")}), strict=False)
    return calculate_cargo_metrics(payload, strict=False)


# 실데이터는 예시 데이터와 달리 비어 있는 칸이 있습니다. 항공사 시간표에는
# 정시율이 없고, 어떤 선사는 소요일을 주지 않습니다. 정렬하다 터지지 않게
# 빈 값은 "모름"으로 두고 뒤로 보냅니다.
_MISSING_DAYS = 10 ** 6
_MISSING_PRICE = float("inf")


def _number(value, fallback: float) -> float:
    return fallback if value is None else value


def _sort_schedules(items: list[dict], sort_by: str) -> list[dict]:
    def price(item):
        return _number(item.get("freight_usd"), _MISSING_PRICE)

    def days(item):
        return _number(item.get("transit_days"), _MISSING_DAYS)

    if sort_by == "price":
        return sorted(items, key=lambda item: (price(item), days(item)))
    if sort_by == "duration":
        return sorted(items, key=lambda item: (days(item), price(item)))
    # Recommended: arrive in time first, then reliability, direct service, price.
    return sorted(items, key=lambda item: (
        not (item.get("deadline") or {}).get("on_time", True),
        -_number(item.get("reliability"), 0),
        not item.get("direct"),
        price(item),
    ))


# 화물을 아직 적지 않았을 때 쓰는 자리표시 값. 출항 일정만 보여 주고 운임은 내지 않습니다.
# (운임은 부피·무게로 정해지므로, 화물 없이 계산하면 틀린 값을 보여 주게 됩니다)
PLACEHOLDER_METRICS = {
    "container_quantity": 1, "container_type": "20FT",
    "billable_revenue_ton": 1.0, "chargeable_weight_kg": 1000.0,
    "total_cbm": 0.0, "total_weight_kg": 0.0,
}
NO_CARGO_NOTE = ("화물 정보를 아직 적지 않아 출항 일정만 보여 드립니다. "
                 "운임은 품목의 크기·무게를 적어야 계산할 수 있습니다.")


def search_schedules(payload: dict) -> dict:
    """Validate route and cargo, then return sorted schedules with deadline checks.

    화물을 아직 적지 않았어도 날짜·출발지·도착지만 있으면 일정을 보여 줍니다.
    그때는 운임을 비우고 그렇다고 알려 줍니다. (서류 작성 화면이 이렇게 부릅니다)
    """

    route = validate_route(payload)
    origin, destination = _resolve_locations(route, payload)
    try:
        metrics = cargo_metrics(payload)
        cargo_known = True
    except ValidationError:
        metrics = dict(PLACEHOLDER_METRICS)
        cargo_known = False
    buyer_required_date = parse_date(payload.get("buyer_required_date"), "Buyer 요청일", required=False,
                                     field="buyer_required_date")

    result = schedule_client.fetch_schedules(
        transport_mode=route["transport_mode"],
        sea_mode=route["sea_mode"],
        origin=origin,
        destination=destination,
        departure_date=route["requested_departure_date"],
        metrics=metrics,
    )
    if not result["success"]:
        raise ServiceError(result["message"], result["error_code"], 502)

    items = result["data"]
    for item in items:
        deadline = check_buyer_deadline(date.fromisoformat(item["eta"]), buyer_required_date, route["transport_mode"])
        if deadline:
            item["deadline"] = {**deadline, "latest_eta": deadline["latest_eta"].isoformat()}
        if not cargo_known:
            # 자리표시 화물로 낸 운임은 내보내지 않습니다. 없는 값을 있는 것처럼 보이면 안 됩니다.
            item["freight_usd"] = None
            item["freight_basis"] = ""
            item["freight_source"] = ""

    sort_by = payload.get("sort") if payload.get("sort") in SORT_OPTIONS else "recommended"
    note = result.get("note", "")
    if not cargo_known:
        note = f"{note} {NO_CARGO_NOTE}".strip()
    return {
        "items": _sort_schedules(items, sort_by),
        "sort": sort_by,
        "source": result["source"],
        # 실데이터인지 예시인지, 예시라면 무엇이 없어서인지 화면에 그대로 적습니다.
        "note": note,
        "metrics": metrics,
        "cargo_known": cargo_known,
    }


def estimate_transit_days(transport_mode: str, sea_mode: str | None, destination: dict,
                          origin_code: str = "") -> int:
    """구간별 최단 운송 소요일. 실제 항로 거리로 계산합니다.

    해상은 FCL·LCL을 구분합니다. LCL은 CFS 혼재·적출 작업만큼 더 걸립니다.
    """

    fallback = DEFAULT_TRANSIT_DAYS["AIR" if transport_mode == "AIR" else "SEA"]
    if not destination:
        return fallback
    summary = transit_summary(origin_code, destination["code"])
    if transport_mode == "AIR":
        return summary["air"]["min"] if summary.get("air") else fallback
    days = (summary.get("sea") or {}).get(sea_mode or "FCL")
    return days["min"] if days else fallback


# 출발지를 아직 고르지 않았을 때 기준으로 삼는 대표 관문.
DEFAULT_ORIGIN = {"port": "KRPUS", "airport": "ICN"}


def _korean_origin(origin: dict | None, kind: str) -> dict | None:
    """해상·항공 각각의 국내 출발 지점을 정합니다.

    고른 곳이 같은 종류면 그대로 쓰고, 다른 종류면 가장 가까운 국내 지점으로
    바꿉니다. 아직 아무것도 고르지 않았으면 대표 관문을 씁니다.
    """

    if origin and origin["kind"] == kind:
        return origin
    if origin:
        return location_client.nearest(origin, kind, "KR")
    return location_client.find_location(DEFAULT_ORIGIN[kind])


def _sea_leg(origin: dict | None, destination: dict | None) -> dict | None:
    """해상 구간: 고른 곳이 공항이면 같은 나라의 가장 가까운 항구로 바꿔 계산합니다."""

    origin = _korean_origin(origin, "port")
    destination = (destination if destination and destination["kind"] == "port"
                   else location_client.nearest(destination, "port"))
    if not origin or not destination:
        return None
    route = location_client.sea_route(origin["code"], destination["code"])
    if not route:
        return None
    return {"origin": origin, "destination": destination, **route}


def _air_leg(origin: dict | None, destination: dict | None) -> dict | None:
    """항공 구간: 고른 곳이 항구면 같은 나라의 가장 가까운 공항으로 바꿔 계산합니다."""

    picked = origin is not None and origin["kind"] == "airport"
    origin = _korean_origin(origin, "airport")
    destination = (destination if destination and destination["kind"] == "airport"
                   else location_client.nearest(destination, "airport"))
    if not origin or not destination or origin["lat"] is None or destination["lat"] is None:
        return None

    # 항구를 골라서 공항을 대신 정한 경우에는, 그 목적지로 직항이 있는 공항을
    # 먼저 씁니다. 거리만 보면 제주처럼 그 노선이 없는 공항이 뽑힙니다.
    if not picked:
        direct_from = destination.get("direct_from") or []
        if origin["code"] not in direct_from:
            better = next((location_client.find_location(code)
                           for code in location_client.korean_air_gateways()
                           if code in direct_from), None)
            origin = better or location_client.find_location(DEFAULT_ORIGIN["airport"]) or origin
    distance = great_circle_km((origin["lat"], origin["lon"]), (destination["lat"], destination["lon"]))
    direct = origin["code"] in (destination.get("direct_from") or [])
    # 직항이면 공표 시간표의 실제 운항 시간을 씁니다.
    minutes = (destination.get("flight_minutes") or {}).get(origin["code"]) if direct else None
    return {"origin": origin, "destination": destination,
            "distance_km": distance, "direct": direct, "minutes": minutes}


def transit_summary(origin_code: str, destination_code: str) -> dict:
    """선택한 구간의 실제 소요일. 해상은 FCL·LCL을 나눠서 계산합니다.

    해상 거리는 실제 항로망에서 구한 값이고, 항공 거리는 공항 사이 대권거리입니다.
    계산 근거는 app/processors/transit_calculator.py에 있습니다.
    """

    destination = location_client.find_location(destination_code)
    if not destination:
        return {"available": False}
    origin = location_client.find_location(origin_code) if origin_code else None

    result = {"available": True, "destination": destination["name"],
              "kind": destination["kind"], "source": "searoute · OurAirports"}

    sea = _sea_leg(origin, destination)
    if sea:
        # 직기항 여부는 출발항과 도착국을 함께 봐야 합니다. 도착항만 보면
        # 광양항처럼 그 나라 항로가 없는 곳에서도 직기항으로 나옵니다.
        lane = location_client.sea_lane_direct(sea["origin"]["code"],
                                               sea["destination"]["country_code"])
        direct = lane["direct"] if lane["known"] else sea["destination"].get("sea_direct")
        result["sea"] = {
            mode: transit_calculator.sea_transit(
                sea["distance_km"], sea["passages"], mode,
                direct=direct, region=sea["destination"]["region"])
            for mode in ("FCL", "LCL")
        }
        result["sea_route"] = {"origin": sea["origin"]["name"], "destination": sea["destination"]["name"],
                               "origin_code": sea["origin"]["code"],
                               "distance_km": sea["distance_km"], "passages": sea["passages"],
                               "transship": direct is False,
                               "lane_known": lane["known"],
                               "direct_from": lane.get("alternatives") or []}

    air = _air_leg(origin, destination)
    if air:
        result["air"] = transit_calculator.air_transit(
            air["distance_km"], transfers=0 if air["direct"] else 1, minutes=air["minutes"])
        result["air_route"] = {"origin": air["origin"]["name"], "destination": air["destination"]["name"],
                               "origin_code": air["origin"]["code"], "destination_code": air["destination"]["code"],
                               "distance_km": round(air["distance_km"]), "direct": air["direct"]}
    return result


MODE_LABELS = {"SEA": "해상", "AIR": "항공"}
# HS 검색 목록 한 번에 협정을 요약해 줄 최대 후보 수
MAX_TARIFF_SUMMARIES = 12

# FCL·LCL을 고르면 실제로 무엇이 달라지는지. 소요일은 항로마다 계산해 채웁니다.
SEA_MODE_FACTS = {
    "FCL": ["컨테이너 한 대를 단독으로 씁니다. 다른 화주 화물과 섞이지 않습니다.",
            "CY(컨테이너 야적장)에서 바로 반입·반출해 CFS 작업이 없습니다.",
            "운임은 컨테이너 한 대 단위로 매깁니다."],
    "LCL": ["다른 화주 화물과 한 컨테이너에 혼재합니다.",
            "출발지 CFS에서 적입하고 도착지 CFS에서 적출·분류하는 시간이 더 듭니다.",
            "운임은 CBM(부피)과 중량 중 큰 쪽으로 매기고, CFS 작업료가 따로 붙습니다."],
}


def sea_mode_difference(summary: dict, selected: str) -> dict | None:
    """고른 해상 운송 방식이 반대쪽과 무엇이 다른지 정리합니다."""

    sea = summary.get("sea") or {}
    if not sea.get("FCL") or not sea.get("LCL"):
        return None
    # 화면이 보낸 값이 FCL·LCL이 아니면 비교할 것이 없습니다.
    if selected not in SEA_MODE_FACTS:
        return None
    other = "LCL" if selected == "FCL" else "FCL"
    gap_min = sea["LCL"]["min"] - sea["FCL"]["min"]
    gap_max = sea["LCL"]["max"] - sea["FCL"]["max"]
    gap = f"{gap_min}일" if gap_min == gap_max else f"{gap_min}~{gap_max}일"
    # LCL에만 붙는 작업을 소요일 내역에서 그대로 가져옵니다.
    extra = [f"{name} {days:g}일" for name, days in sea["LCL"]["breakdown"].items()
             if name not in sea["FCL"]["breakdown"]]
    return {
        "selected": selected,
        "other": other,
        "facts": SEA_MODE_FACTS[selected],
        "gap_days": gap,
        "extra_steps": extra,
        "summary": (f"LCL은 {' · '.join(extra)}이 더해져 FCL보다 {gap} 깁니다."
                    if extra else f"LCL이 FCL보다 {gap} 깁니다."),
    }
# 환승 1회에 더해지는 일수 (연결편 대기·재적재)
TRANSFER_EXTRA_DAYS = 1


def air_route_status(origin_code: str, destination_code: str) -> dict:
    """선택한 출발 공항에서 목적 공항까지 직항편이 있는지 확인합니다."""

    destination = location_client.find_location(destination_code)
    if not destination or destination["kind"] != "airport":
        return {"known": False}

    direct_from = destination.get("direct_from") or []
    origin_code = str(origin_code or "").strip().upper()
    if origin_code and origin_code in direct_from:
        return {"known": True, "direct": True, "origin": origin_code}

    # 다른 국내 공항에서는 직항이 있는지, 없으면 경유 공항을 안내합니다.
    alternatives = [code for code in direct_from if code != origin_code]
    return {
        "known": True,
        "direct": False,
        "origin": origin_code,
        "korea_alternatives": alternatives,
        "transfer_via": [code for code, _ in (destination.get("transfer_via") or [])],
    }


def schedule_outlook(payload: dict) -> dict:
    """선택한 구간의 해상·항공 소요시간과 납기 여유를 함께 계산합니다.

    화면 왼쪽 달력 아래에 표시합니다. 여유는 가장 오래 걸리는 스케줄(보수적)
    기준으로 등급을 매기고, 가장 빠른 스케줄 기준 여유도 함께 돌려줍니다.
    """

    departure = parse_date(payload.get("requested_departure_date"), "Seller 발송 예상일", required=False,
                           field="requested_departure_date")
    buyer_required = parse_date(payload.get("buyer_required_date"), "Buyer 요청일", required=False,
                                field="buyer_required_date")
    origin_code = str(payload.get("origin_code") or "")
    destination_code = str(payload.get("destination_code") or "")
    summary = transit_summary(origin_code, destination_code)
    if not departure or not summary.get("available"):
        return {"available": False}

    # 항구를 골랐으면 가장 가까운 공항으로 바꿔 항공편을 확인합니다.
    air_route = summary.get("air_route") or {}
    route = air_route_status(air_route.get("origin_code", origin_code),
                             air_route.get("destination_code", destination_code))
    air_origin = air_route.get("origin_code") or origin_code
    air_note = ""
    # 정기편이 멈춘 공항이면 소요일보다 그 사실을 먼저 알려야 합니다.
    stopped = location_client.airport_service_status(air_origin)
    if not stopped["operating"]:
        air_note = f"{stopped['reason']} {stopped['detail']}"
    elif route.get("known") and not route.get("direct"):
        # 직항이 없으면 어디서 출발하거나 어디를 경유해야 하는지 알려줍니다.
        if route["korea_alternatives"]:
            air_note = (f"{air_origin} 출발 직항 없음 · "
                        f"{', '.join(route['korea_alternatives'])} 출발은 직항")
        elif route["transfer_via"]:
            air_note = f"직항 없음 · {', '.join(route['transfer_via'])} 경유"
        else:
            air_note = "직항 없음 · 환승 필요"

    sea_route = summary.get("sea_route") or {}
    sea_note = ""
    if sea_route.get("transship"):
        others = sea_route.get("direct_from") or []
        names = [(location_client.find_location(code) or {}).get("name", code) for code in others]
        sea_note = (f"{sea_route['origin']} 출발 직기항 없음 · {' · '.join(names)} 출발은 직기항"
                    if names else "한국 직기항 없음 · 환적 포함")
    else:
        # 소요일에 영향을 주는 길목만 안내합니다.
        labels = {"suez": "수에즈 운하", "panama": "파나마 운하", "south_africa": "희망봉"}
        passed = [labels[p] for p in sea_route.get("passages", []) if p in labels]
        sea_note = f"{' · '.join(passed)} 경유" if passed else ""

    # 화면에서 고른 운송 방식. 해당 줄을 강조하고 무엇이 달라지는지 안내합니다.
    selected_mode = str(payload.get("transport_mode") or "").upper()
    selected_sea = str(payload.get("sea_mode") or "FCL").upper()

    plans = []
    for sea_mode in ("FCL", "LCL"):
        days = (summary.get("sea") or {}).get(sea_mode)
        if days:
            plans.append(("SEA", sea_mode, days, sea_note))
    if summary.get("air"):
        plans.append(("AIR", None, summary["air"], air_note))

    modes = []
    for mode, sea_mode, days, note in plans:
        entry = {
            "mode": mode,
            "sea_mode": sea_mode,
            "selected": mode == selected_mode and (sea_mode is None or sea_mode == selected_sea),
            "label": f"{MODE_LABELS[mode]} {sea_mode}" if sea_mode else MODE_LABELS[mode],
            "note": note,
            "direct": route.get("direct") if mode == "AIR" else not sea_route.get("transship"),
            "distance_km": days["distance_km"],
            "breakdown": days["breakdown"],
            "min_days": days["min"],
            "max_days": days["max"],
            "eta_fastest": calculate_eta(departure, days["min"]).isoformat(),
            "eta_slowest": calculate_eta(departure, days["max"]).isoformat(),
        }
        if buyer_required:
            fastest = check_departure_margin(departure, buyer_required, mode, days["min"])
            slowest = check_departure_margin(departure, buyer_required, mode, days["max"])
            entry.update({
                "margin_best": fastest["margin_days"],
                "margin_worst": slowest["margin_days"],
                "level": slowest["level"],          # 보수적으로 판단합니다.
                "status": slowest["label"],
            })
        else:
            entry.update({"margin_best": None, "margin_worst": None,
                          "level": "none", "status": "Buyer 요청일 미입력"})
        modes.append(entry)

    return {
        "available": True,
        "destination": summary["destination"],
        "departure_date": departure.isoformat(),
        "buyer_required_date": buyer_required.isoformat() if buyer_required else None,
        "modes": modes,
        "sea_route": summary.get("sea_route"),
        "air_route": summary.get("air_route"),
        "sea_mode_diff": sea_mode_difference(summary, selected_sea) if selected_mode == "SEA" else None,
        "source": summary["source"],
    }


def check_departure_date(payload: dict) -> dict:
    """출발 희망일이 Buyer 요청 도착일에 맞는지 확인합니다.

    화면 왼쪽 달력 아래의 "Seller 예정일" 표시에 씁니다.
    """

    transport_mode = str(payload.get("transport_mode") or "SEA").upper()
    departure = parse_date(payload.get("requested_departure_date"), "출발 희망일", required=False,
                           field="requested_departure_date")
    buyer_required = parse_date(payload.get("buyer_required_date"), "Buyer 요청일", required=False,
                                field="buyer_required_date")
    if not departure:
        return {"available": False, "reason": "출발 희망일을 선택해주세요."}

    destination = location_client.find_location(str(payload.get("destination_code") or "")) or {}
    transit_days = estimate_transit_days(transport_mode, payload.get("sea_mode"), destination,
                                         str(payload.get("origin_code") or ""))
    eta = calculate_eta(departure, transit_days)
    result = {
        "available": True,
        "departure_date": departure.isoformat(),
        "transit_days": transit_days,
        "eta": eta.isoformat(),
        "destination": destination.get("name", ""),
        "estimated": not destination,
    }
    if not buyer_required:
        result.update({"level": "none", "label": "Buyer 요청일 미입력", "margin_days": None})
        return result

    margin = check_departure_margin(departure, buyer_required, transport_mode, transit_days)
    result.update({
        "buyer_required_date": buyer_required.isoformat(),
        "latest_etd": margin["latest_etd"].isoformat(),
        "margin_days": margin["margin_days"],
        "level": margin["level"],
        "label": margin["label"],
    })
    return result


def cargo_items(payload: dict) -> list[dict]:
    """화물 입력을 품목 목록으로 만듭니다.

    화면에서 품목을 여러 개 보낼 수 있고, 예전처럼 한 건만 보내도 그대로 받습니다.
    """

    # 화면이 늘 올바른 모양을 보내리라 믿지 않습니다. 이상하면 빈 목록으로 둡니다.
    cargo = (payload if isinstance(payload, dict) else {}).get("cargo") or {}
    if isinstance(cargo, list):
        items = cargo
    elif isinstance(cargo, dict):
        items = cargo.get("items")
    else:
        return []
    if not isinstance(items, list):
        items = [cargo] if isinstance(cargo, dict) and cargo else []
    return [item for item in items if isinstance(item, dict) and item]


def cargo_metrics(payload: dict, *, strict: bool = False) -> dict:
    """품목이 하나든 여럿이든 같은 모양의 계산 결과를 돌려줍니다.

    스케줄 조회처럼 아직 입력 중일 때 부르는 곳이 많아 기본은 느슨하게 봅니다.
    저장할 때는 create_shipment가 strict로 다시 확인합니다.
    """

    return calculate_cargo_lines(cargo_items(payload), strict=strict)


def create_shipment(payload: dict, user_id: int | None = None) -> Shipment:
    """Create a quoted Shipment from the planning wizard.

    user_id is the member who owns it; only they and the master can see it.

    Every value is re-validated and recalculated on the server; the selected
    schedule is looked up again rather than trusting client-side freight.
    """

    route = validate_route(payload)
    origin, destination = _resolve_locations(route, payload)
    parties = validate_parties(payload)

    items = cargo_items(payload)
    metrics = calculate_cargo_lines(items)
    # 품목별 금액을 모두 적었으면 그 합을 송장 금액으로 씁니다.
    # 화면이 보낸 합계는 믿지 않고 서버에서 다시 더합니다.
    if metrics["amount"] is not None:
        payload = {**payload, "invoice_value": metrics["amount"]}
    terms = validate_trade_terms(payload, route["transport_mode"])
    cargo_payload = items[0]
    product_description = optional_text(cargo_payload.get("product_description"), max_length=300)
    if not product_description:
        raise ValidationError("품명(Product Description)을 입력해주세요.", "product_description")
    hs_code = optional_text(cargo_payload.get("hs_code"), max_length=20)
    # 순중량은 품목별로 calculate_cargo_lines에서 이미 확인했습니다.

    schedule_id = str(payload.get("schedule_id") or "")
    if not schedule_id:
        raise ValidationError("스케줄을 선택해주세요.", "schedule_id")
    schedules = search_schedules(payload)
    schedule = next((item for item in schedules["items"] if item["schedule_id"] == schedule_id), None)
    if schedule is None:
        raise ValidationError("선택한 스케줄을 찾을 수 없습니다. 스케줄을 다시 조회해주세요.", "schedule_id")

    buyer_required_date = parse_date(payload.get("buyer_required_date"), "Buyer 요청일", required=False,
                                     field="buyer_required_date")
    rates_result = exchange_client.fetch_krw_rates()
    rates = rates_result["data"]
    invoice_value_usd = exchange_client.convert(terms["invoice_value"], terms["currency"], "USD", rates)

    costs = calculate_logistics_cost(
        transport_mode=route["transport_mode"],
        sea_mode=route["sea_mode"],
        incoterms=terms["incoterms"],
        freight_usd=schedule["freight_usd"],
        freight_source=schedule["source"],
        invoice_value_usd=invoice_value_usd,
        metrics=metrics,
        exchange_rate=rates["USD"],
        exchange_source=rates_result["source"],
    )

    buyer = buyer_repository.get_or_create(
        parties["buyer_name"], parties["buyer_country"] or destination["country"],
        parties["buyer_address"], parties["buyer_email"],
    )
    etd = date.fromisoformat(schedule["etd"])
    eta = date.fromisoformat(schedule["eta"])

    shipment = Shipment(
        shipment_id=shipment_repository.next_shipment_id(date.today().year),
        project_name=route["project_name"],
        user_id=user_id,
        buyer=buyer,
        trade_type="export",
        transport_mode=route["transport_mode"],
        sea_mode=route["sea_mode"],
        origin_code=origin["code"],
        origin_name=origin["name_en"],
        destination_code=destination["code"],
        destination_name=destination["name_en"],
        destination_country=destination["country_code"],
        requested_departure_date=route["requested_departure_date"],
        cargo_ready_date=calculate_cargo_ready_date(etd, route["transport_mode"]),
        etd=etd,
        eta=eta,
        planned_eta=eta,
        buyer_required_date=buyer_required_date,
        incoterms=terms["incoterms"],
        currency=terms["currency"],
        invoice_value=terms["invoice_value"],
        exporter_name=parties["exporter_name"],
        exporter_address=parties["exporter_address"],
        notify_party=parties["notify_party"],
        carrier=schedule["carrier"],
        vessel_or_flight=schedule["vessel_or_flight"],
        transit_days=schedule["transit_days"],
        is_direct=schedule["direct"],
        freight_usd=schedule["freight_usd"],
        schedule_source=schedule["source"],
        status="quoted",
    )
    is_fcl = route["sea_mode"] == "FCL"
    shipment.cargos = [
        Cargo(
            line_no=index,
            product_description=optional_text(item.get("product_description"), max_length=300)
            or product_description,
            hs_code=optional_text(item.get("hs_code"), max_length=20) or hs_code,
            package_type=line["package_type"],
            is_dangerous=line["is_dangerous"],
            temperature_requirement=line["temperature_requirement"],
            special_container_type=line["special_container_type"],
            un_number=line["un_number"],
            dg_class=line["dg_class"],
            packing_group=line["packing_group"],
            proper_shipping_name=line["proper_shipping_name"],
            length_cm=line["length_cm"],
            width_cm=line["width_cm"],
            height_cm=line["height_cm"],
            quantity=line["quantity"],
            weight_per_package_kg=line["weight_per_package_kg"],
            # 품목마다 순중량을 따로 적습니다.
            net_weight_kg=line["net_weight_kg"],
            # 품목마다 단가·금액을 따로 적습니다. (송장의 Unit price / Amount 칸)
            unit_price=line["unit_price"],
            amount=line["amount"],
            # 단가를 낱개로 매겼으면 그 기준을 같이 남깁니다. 없으면 포장 개수가 기준입니다.
            unit_quantity=line["unit_quantity"],
            price_unit=line["price_unit"],
            units_per_package=line["units_per_package"],
            total_cbm=line["total_cbm"],
            total_weight_kg=line["total_weight_kg"],
            revenue_ton=line["revenue_ton"],
            chargeable_weight_kg=line["chargeable_weight_kg"],
            # 컨테이너는 화물을 모두 더한 뒤에 정해지므로 첫 품목에만 적습니다.
            container_type=metrics["container_type"] if is_fcl and index == 1 else None,
            container_quantity=metrics["container_quantity"] if is_fcl and index == 1 else None,
        )
        for index, (item, line) in enumerate(zip(items, metrics["lines"]), start=1)
    ]
    shipment_repository.add(shipment)
    shipment_repository.replace_costs(shipment, costs["lines"])
    shipment_repository.commit()
    return shipment
