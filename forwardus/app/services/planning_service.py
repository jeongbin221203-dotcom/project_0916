"""Shipment planning: locations, cargo, schedules, reverse planner, shipment creation."""

from __future__ import annotations

from datetime import date

from app.collectors import customs_client, exchange_client, location_client, schedule_client
from app.models import Cargo, Shipment
from app.processors.cargo_calculator import calculate_cargo_metrics
from app.processors.cost_calculator import INCOTERMS_INFO, calculate_logistics_cost
from app.processors.schedule_calculator import (
    calculate_cargo_ready_date,
    calculate_reverse_schedule,
    check_buyer_deadline,
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


def location_kind(transport_mode: str) -> str:
    return "airport" if transport_mode == "AIR" else "port"


def get_form_options() -> dict:
    """Static options the planning form needs on first render."""

    return {
        "incoterms": INCOTERMS_INFO,
        "package_types": PACKAGE_TYPES,
        "sort_options": SORT_OPTIONS,
        "currencies": ["USD", "EUR", "JPY", "CNY", "KRW"],
    }


def search_locations(query: str, transport_mode: str, role: str | None = None, country: str | None = None) -> dict:
    """Search ports or airports. Export flow: origin in Korea, destination abroad."""

    if role == "origin":
        country = "KR"
    result = location_client.search_locations(query, location_kind(transport_mode.upper()), country)
    if result["success"] and role == "destination":
        result["data"] = [item for item in result["data"] if item["country_code"] != "KR"]
    return result


def list_countries(transport_mode: str, role: str | None = None) -> dict:
    """Destination country list for the country filter."""

    return location_client.list_countries(
        location_kind(transport_mode.upper()), exclude=["KR"] if role == "destination" else None
    )


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
    field = f"{role}_code"
    if not code.isalnum() or not location_client.CODE_MIN_LENGTH <= len(code) <= location_client.CODE_MAX_LENGTH:
        raise ValidationError(
            f"코드는 영문·숫자 {location_client.CODE_MIN_LENGTH}~{location_client.CODE_MAX_LENGTH}자로 입력해주세요. (예: KRPUS)",
            field)

    country_code = "KR" if role == "origin" else str(custom.get("country_code") or "").strip().upper()
    country = location_client.get_country(country_code)
    if not country:
        raise ValidationError("국가를 선택해주세요.", f"{role}_country")

    name = optional_text(custom.get("name"), max_length=200)
    if not name:
        raise ValidationError("항구·공항 이름을 입력해주세요.", f"{role}_name")

    return {
        "code": code,
        "name": name,
        "name_en": name,
        "city": name,
        "city_en": name,
        "country": country["name"],
        "country_en": country["name_en"],
        "country_code": country_code,
        "region": country["region"],
        "kind": kind,
        "major": False,
        "source": "manual",
    }


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
