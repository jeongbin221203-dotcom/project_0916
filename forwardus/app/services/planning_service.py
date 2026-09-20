"""Shipment planning: locations, cargo, schedules, reverse planner, shipment creation."""

from __future__ import annotations

from datetime import date

from app.collectors import customs_client, exchange_client, location_client, schedule_client
from app.collectors.base_client import load_mock
from app.models import Cargo, Shipment
from app.processors.cargo_calculator import calculate_cargo_metrics
from app.processors.cost_calculator import INCOTERMS_INFO, calculate_logistics_cost
from app.processors import transit_calculator
from app.processors.transit_calculator import great_circle_km
from app.processors.schedule_calculator import (
    DEFAULT_TRANSIT_DAYS,
    calculate_eta,
    calculate_cargo_ready_date,
    calculate_reverse_schedule,
    check_buyer_deadline,
    check_departure_margin,
)
from app.repositories import buyer_repository, shipment_repository
from app.services import ServiceError
from app.validators import ValidationError
from app.validators.cargo_validator import PACKAGE_TYPES
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
        "package_types": PACKAGE_TYPES,
        "sort_options": SORT_OPTIONS,
        "currencies": exchange_client.list_currencies(),
    }


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


def search_hs_codes(query: str) -> dict:
    return customs_client.search_hs_codes(query)


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
    return calculate_cargo_metrics(payload)


def _sort_schedules(items: list[dict], sort_by: str) -> list[dict]:
    if sort_by == "price":
        return sorted(items, key=lambda item: (item["freight_usd"], item["transit_days"]))
    if sort_by == "duration":
        return sorted(items, key=lambda item: (item["transit_days"], item["freight_usd"]))
    # Recommended: arrive in time first, then reliability, direct service, price.
    return sorted(items, key=lambda item: (
        not (item.get("deadline") or {}).get("on_time", True),
        -item["reliability"],
        not item["direct"],
        item["freight_usd"],
    ))


def search_schedules(payload: dict) -> dict:
    """Validate route and cargo, then return sorted schedules with deadline checks."""

    route = validate_route(payload)
    origin, destination = _resolve_locations(route, payload)
    metrics = calculate_cargo_metrics(payload.get("cargo") or {})
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

    sort_by = payload.get("sort") if payload.get("sort") in SORT_OPTIONS else "recommended"
    return {
        "items": _sort_schedules(items, sort_by),
        "sort": sort_by,
        "source": result["source"],
        "metrics": metrics,
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

    origin = _korean_origin(origin, "airport")
    destination = (destination if destination and destination["kind"] == "airport"
                   else location_client.nearest(destination, "airport"))
    if not origin or not destination or origin["lat"] is None or destination["lat"] is None:
        return None
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
        result["sea"] = {
            mode: transit_calculator.sea_transit(
                sea["distance_km"], sea["passages"], mode,
                direct=sea["destination"].get("sea_direct"), region=sea["destination"]["region"])
            for mode in ("FCL", "LCL")
        }
        result["sea_route"] = {"origin": sea["origin"]["name"], "destination": sea["destination"]["name"],
                               "distance_km": sea["distance_km"], "passages": sea["passages"],
                               "transship": sea["destination"].get("sea_direct") is False}

    air = _air_leg(origin, destination)
    if air:
        result["air"] = transit_calculator.air_transit(
            air["distance_km"], transfers=0 if air["direct"] else 1, minutes=air["minutes"])
        result["air_route"] = {"origin": air["origin"]["name"], "destination": air["destination"]["name"],
                               "origin_code": air["origin"]["code"], "destination_code": air["destination"]["code"],
                               "distance_km": round(air["distance_km"]), "direct": air["direct"]}
    return result


MODE_LABELS = {"SEA": "해상", "AIR": "항공"}

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
    origin_code = (origin_code or "").strip().upper()
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

    departure = parse_date(payload.get("requested_departure_date"), "Seller 예상일", required=False,
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
    if route.get("known") and not route.get("direct"):
        # 직항이 없으면 어디서 출발하거나 어디를 경유해야 하는지 알려줍니다.
        if route["korea_alternatives"]:
            air_note = f"{air_origin} 직항 없음 · {', '.join(route['korea_alternatives'])} 출발은 직항"
        elif route["transfer_via"]:
            air_note = f"직항 없음 · {', '.join(route['transfer_via'])} 경유"
        else:
            air_note = "직항 없음 · 환승 필요"

    sea_route = summary.get("sea_route") or {}
    sea_note = ""
    if sea_route.get("transship"):
        sea_note = "한국 직기항 없음 · 환적 포함"
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


def reverse_schedule(payload: dict) -> dict:
    buyer_required_date = parse_date(payload.get("buyer_required_date"), "Buyer 요청일", field="buyer_required_date")
    transport_mode = str(payload.get("transport_mode") or "SEA").upper()
    transit_days = payload.get("transit_days")
    try:
        transit_days = int(transit_days) if transit_days not in (None, "") else None
    except (TypeError, ValueError) as exc:
        raise ValidationError("운송 기간은 정수로 입력해주세요.", "transit_days") from exc
    if transit_days is not None and not 0 < transit_days <= 90:
        raise ValidationError("운송 기간은 1~90일 사이로 입력해주세요.", "transit_days")

    plan = calculate_reverse_schedule(buyer_required_date, transport_mode, transit_days)
    warnings = []
    if plan["cargo_ready_date"] < date.today():
        warnings.append("출고 준비일이 이미 지났습니다. 항공 운송 또는 Buyer와 납기 조정을 검토하세요.")
    return {
        **{key: (value.isoformat() if isinstance(value, date) else value) for key, value in plan.items() if key != "steps"},
        "steps": [
            {**step, "date": step["date"].isoformat()} if "date" in step else step for step in plan["steps"]
        ],
        "warnings": warnings,
    }


def create_shipment(payload: dict) -> Shipment:
    """Create a quoted Shipment from the planning wizard.

    Every value is re-validated and recalculated on the server; the selected
    schedule is looked up again rather than trusting client-side freight.
    """

    route = validate_route(payload)
    origin, destination = _resolve_locations(route, payload)
    terms = validate_trade_terms(payload, route["transport_mode"])
    parties = validate_parties(payload)

    cargo_payload = payload.get("cargo") or {}
    metrics = calculate_cargo_metrics(cargo_payload)
    product_description = optional_text(cargo_payload.get("product_description"), max_length=300)
    if not product_description:
        raise ValidationError("품명(Product Description)을 입력해주세요.", "product_description")
    hs_code = optional_text(cargo_payload.get("hs_code"), max_length=20)
    net_weight = validate_net_weight(cargo_payload.get("net_weight_kg"), metrics["total_weight_kg"])

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
    shipment.cargo = Cargo(
        product_description=product_description,
        hs_code=hs_code,
        package_type=metrics["package_type"],
        length_cm=metrics["length_cm"],
        width_cm=metrics["width_cm"],
        height_cm=metrics["height_cm"],
        quantity=metrics["quantity"],
        weight_per_package_kg=metrics["weight_per_package_kg"],
        net_weight_kg=net_weight,
        total_cbm=metrics["total_cbm"],
        total_weight_kg=metrics["total_weight_kg"],
        revenue_ton=metrics["revenue_ton"],
        chargeable_weight_kg=metrics["chargeable_weight_kg"],
        container_type=metrics["container_type"] if route["sea_mode"] == "FCL" else None,
        container_quantity=metrics["container_quantity"] if route["sea_mode"] == "FCL" else None,
    )
    shipment_repository.add(shipment)
    shipment_repository.replace_costs(shipment, costs["lines"])
    shipment_repository.commit()
    return shipment
