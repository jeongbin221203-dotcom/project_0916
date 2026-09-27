"""선사·항공사 스케줄.

키가 있으면 실제 스케줄을 쓰고, 없으면 예시 스케줄로 돌아갑니다.
- 해상: HMM 항구간 스케줄 (실제 항차·환적항·소요일)
- 항공: 인천국제공항공사 화물기 정기운항 일정 (실제 화물편 시간표)

운임은 어느 API도 주지 않습니다. 계약 단가라 공개되지 않기 때문입니다.
그래서 스케줄이 실데이터여도 운임은 늘 추정값이고, 항목마다
``freight_source = "estimate"``로 표시해 화면에서 구분합니다.
"""

from __future__ import annotations

from datetime import date, timedelta

from app.collectors import carrier_client
from app.collectors.base_client import fail, load_mock, ok

# 실제 화물편 시간표에서 앞으로 며칠 치를 뽑아 보여줄지.
AIR_SCHEDULE_HORIZON_DAYS = 14
MAX_LIVE_ITEMS = 12


def fetch_schedules(
    *,
    transport_mode: str,
    sea_mode: str | None,
    origin: dict,
    destination: dict,
    departure_date: date,
    metrics: dict,
) -> dict:
    """Return normalized schedules departing on or after ``departure_date``."""

    service = "AIR" if transport_mode == "AIR" else (sea_mode or "FCL")
    try:
        templates = load_mock("schedules")[service]
    except (OSError, ValueError, KeyError):
        return fail("MOCK_DATA_ERROR", "mock")

    region = destination.get("region", "asia")
    live = (_air_schedules(origin, destination, departure_date)
            if service == "AIR" else
            _sea_schedules(origin, destination, departure_date))
    if live:
        rate = _reference_rate(templates, region)
        for item in live:
            item.update(_freight(service, rate, metrics))
        return {**ok(live[:MAX_LIVE_ITEMS], "api"),
                "note": "스케줄은 선사·공항 실데이터이고 운임은 추정값입니다."}

    items = _mock_schedules(templates, service, region, origin, destination, departure_date, metrics)
    return {**ok(items, "mock"), "note": _missing_key_note(service)}


# --- 실데이터 ----------------------------------------------------------------

def _sea_schedules(origin: dict, destination: dict, departure_date: date) -> list[dict]:
    """HMM 항구간 스케줄. 키가 없거나 결과가 없으면 빈 목록입니다."""

    result = carrier_client.fetch_hmm_schedules(origin["code"], destination["code"], departure_date)
    if not result["success"]:
        return []
    items = []
    for row in result["data"]:
        if not row["etd"] or not row["eta"]:
            continue
        items.append({
            **row,
            "schedule_id": f"HMM-{row['vessel_or_flight']}-{row['etd']}".replace(" ", "_"),
            "service": f"{row['transship_port']} 환적" if row["transship_port"] else "직항",
            "reliability": None,
        })
    return items


def _air_schedules(origin: dict, destination: dict, departure_date: date) -> list[dict]:
    """인천공항 화물기 시간표를 날짜별 출발편으로 펼칩니다.

    시간표는 "무슨 요일에 뜨는지"만 알려주므로, 출발 희망일부터 앞으로
    2주치 가운데 실제로 뜨는 날만 골라 냅니다.
    """

    if origin["code"] != "ICN":
        # 이 API는 인천공항 편만 다룹니다. 김해·김포는 예시 스케줄로 갑니다.
        return []
    result = carrier_client.fetch_icn_cargo_flights(destination["code"])
    if not result["success"]:
        return []

    transit = destination.get("transit_days") or 2
    items, seen = [], set()
    for row in result["data"]:
        if not row["days"]:
            continue
        # 공항공사는 도착 공항으로 이미 걸러 줍니다. 표시되는 공항이 다르면
        # 그곳을 들렀다 가는 편(예: 인천→밀라노→프랑크푸르트)이라 경유로 적습니다.
        via = row["counterpart_code"] if row["counterpart_code"] != destination["code"] else ""
        for offset in range(AIR_SCHEDULE_HORIZON_DAYS):
            etd = departure_date + timedelta(days=offset)
            if "월화수목금토일"[etd.weekday()] not in row["days"]:
                continue
            if row["valid_to"] and etd.isoformat() > row["valid_to"]:
                continue
            schedule = f"{row['days_label']} 운항 · {row['scheduled_time']} 출발".strip(" ·")
            key = (row["vessel_or_flight"], etd.isoformat())
            if key in seen:
                # 같은 편이 유효기간·시즌별로 여러 줄 옵니다. 한 번만 보여줍니다.
                continue
            seen.add(key)
            items.append({
                "schedule_id": f"ICN-{row['vessel_or_flight']}-{etd.isoformat()}",
                "carrier": row["carrier"],
                "vessel_or_flight": row["vessel_or_flight"],
                "service": f"{via} 경유 · {schedule}" if via else schedule,
                "etd": etd.isoformat(),
                # 경유편은 그만큼 늦게 도착합니다.
                "eta": (etd + timedelta(days=transit + (1 if via else 0))).isoformat(),
                "transit_days": transit + (1 if via else 0),
                "direct": not via,
                "transship_port": via,
                "origin_code": origin["code"],
                "destination_code": destination["code"],
                "reliability": None,
                "source": "api",
            })
    return sorted(items, key=lambda item: (item["etd"], not item["direct"], item["carrier"]))


# --- 운임 (늘 추정) -----------------------------------------------------------

def _reference_rate(templates: list[dict], region: str) -> dict | None:
    """예시 요율표에서 그 지역의 기준 단가를 하나 고릅니다."""

    usable = [t for t in templates if region in t["rate_usd"]]
    if not usable:
        return None
    cheapest = min(usable, key=lambda t: t["rate_usd"][region])
    return {"rate": cheapest["rate_usd"][region], "minimum": cheapest.get("minimum_usd", 0)}


def _freight(service: str, rate: dict | None, metrics: dict) -> dict:
    if not rate:
        return {"freight_usd": None, "freight_basis": "", "freight_source": "unknown"}
    if service == "FCL":
        amount = rate["rate"] * metrics["container_quantity"]
        basis = f"{metrics['container_quantity']} × {metrics['container_type']}"
    elif service == "LCL":
        amount = max(rate["rate"] * metrics["billable_revenue_ton"], rate["minimum"])
        basis = f"{metrics['billable_revenue_ton']:.2f} R/T"
    else:
        amount = max(rate["rate"] * metrics["chargeable_weight_kg"], rate["minimum"])
        basis = f"{metrics['chargeable_weight_kg']:,.0f} kg C.W."
    return {"freight_usd": round(amount, 2), "freight_basis": basis, "freight_source": "estimate"}


# --- 예시 스케줄 --------------------------------------------------------------

def _mock_schedules(templates, service, region, origin, destination, departure_date, metrics) -> list[dict]:
    items = []
    for template in templates:
        transit = template["transit_days"].get(region)
        if transit is None:
            continue
        # Weekly service: first sailing on/after the requested date.
        offset = (template["weekday"] - departure_date.weekday()) % 7
        for week in range(2):
            etd = departure_date + timedelta(days=offset + week * 7)
            rate = {"rate": template["rate_usd"][region], "minimum": template.get("minimum_usd", 0)}
            items.append({
                "schedule_id": f"{template['code']}-{etd.isoformat()}",
                "carrier": template["carrier"],
                "vessel_or_flight": template["vessel_or_flight"],
                "service": template["service"],
                "etd": etd.isoformat(),
                "eta": (etd + timedelta(days=transit)).isoformat(),
                "transit_days": transit,
                "direct": template["direct"],
                "reliability": template["reliability"],
                "origin_code": origin["code"],
                "destination_code": destination["code"],
                "source": "mock",
                **_freight(service, rate, metrics),
            })
    return items


def _missing_key_note(service: str) -> str:
    """왜 예시 스케줄인지 정확히 알립니다. "API가 없다"는 말은 사실이 아닙니다."""

    wanted = "icn_cargo" if service == "AIR" else "hmm"
    source = next((s for s in carrier_client.sources() if s["key"] == wanted), None)
    if source and not source["ready"]:
        return (f"{source['label']} 키({source['env']})가 없어 예시 스케줄을 보여줍니다."
                f" {source.get('signup', '')}에서 무료로 발급받으면 실제 스케줄로 바뀝니다.")
    return "이 구간의 실제 스케줄을 받지 못해 예시 스케줄을 보여줍니다."
