"""Schedule, reverse schedule, and shipment creation tests."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.processors.schedule_calculator import (
    calculate_cargo_ready_date,
    calculate_eta,
    calculate_reverse_schedule,
    check_buyer_deadline,
)
from app.services import planning_service
from app.validators import ValidationError


def test_reverse_schedule_matches_spec_example():
    plan = calculate_reverse_schedule(date(2026, 11, 20), "SEA", 14)
    assert plan["recommended_eta"] == date(2026, 11, 16)
    assert plan["recommended_etd"] == date(2026, 11, 2)
    assert plan["cargo_ready_date"] == date(2026, 10, 29)


def test_reverse_schedule_air_defaults():
    plan = calculate_reverse_schedule(date(2026, 11, 20), "AIR")
    assert plan["transit_days"] == 2
    assert plan["recommended_eta"] == date(2026, 11, 18)
    assert plan["recommended_etd"] == date(2026, 11, 16)
    assert plan["cargo_ready_date"] == date(2026, 11, 14)


def test_schedule_date_calculation():
    assert calculate_eta(date(2026, 12, 28), 14) == date(2027, 1, 11)
    assert calculate_cargo_ready_date(date(2026, 11, 2), "SEA") == date(2026, 10, 29)


def test_buyer_deadline_check():
    ok = check_buyer_deadline(date(2026, 11, 10), date(2026, 11, 20), "SEA")
    assert ok["on_time"] and ok["margin_days"] == 6
    late = check_buyer_deadline(date(2026, 11, 19), date(2026, 11, 20), "SEA")
    assert not late["on_time"] and late["margin_days"] == -3
    assert check_buyer_deadline(date(2026, 11, 19), None, "SEA") is None


def test_reverse_schedule_service_validation(app):
    with pytest.raises(ValidationError):
        planning_service.reverse_schedule({"buyer_required_date": "not-a-date"})
    with pytest.raises(ValidationError):
        planning_service.reverse_schedule({"buyer_required_date": "2026-11-20", "transit_days": "0"})


def test_location_search_filters_by_mode_and_role(app):
    ports = planning_service.search_locations("부산", "SEA", "origin")["data"]
    codes = [p["code"] for p in ports]
    assert codes[:2] == ["KRPUS", "KRBNP"]  # 주요 항만·짧은 이름 우선
    assert "KRKCN" in codes  # 감천항(부산)
    assert all(p["country_code"] == "KR" and p["kind"] == "port" for p in ports)
    airports = planning_service.search_locations("los angeles", "AIR", "destination")["data"]
    assert [a["code"] for a in airports] == ["LAX"]
    assert planning_service.search_locations("USLAX", "SEA", "origin")["data"] == []


def test_origin_lists_only_korean_trade_ports(app):
    """출발지는 「항만법」상 무역항과 소속 부두만 노출합니다."""

    from app.collectors import location_client

    all_kr_ports = {
        item["code"] for item in location_client.load_mock("locations")
        if item["country_code"] == "KR" and item["kind"] == "port"
    }
    # 무역항 31곳 + 소속 부두
    assert 30 < len(all_kr_ports) < 50
    for code in ("KRPUS", "KRINC", "KRKAN", "KRUSN", "KRPTK", "KRMAS", "KRKPO", "KRMOK",
                 "KRSEL", "KRHAS", "KRBNP", "KRTGH"):
        assert code in all_kr_ports
        assert planning_service.search_locations(code, "SEA", "origin")["data"][0]["code"] == code
    # 어항·연안항과 중복 코드는 제외합니다.
    assert not (all_kr_ports & {"KRGRP", "KRHPO", "KRJMJ", "KRHDO", "KRULL", "KRTGA", "KRKWA"})
    # 국내 항구는 전부 주요 항구로 표시합니다.
    assert all(item["major"] for item in location_client.load_mock("locations")
               if item["country_code"] == "KR" and item["kind"] == "port")


def test_destination_countries_and_country_filter(app):
    countries = planning_service.list_countries("SEA", "destination")["data"]
    codes = {c["code"] for c in countries}
    assert len(countries) > 150
    assert "KR" not in codes
    assert {"US", "VN", "DE", "AE", "ZA", "BR", "SI"} <= codes
    # 내륙국과 남극은 해상 목적지가 될 수 없습니다.
    assert not ({"AT", "CH", "NP", "HU", "RS", "UZ", "AQ"} & codes)

    vietnam = planning_service.search_locations("", "SEA", "destination", country="VN")["data"]
    assert vietnam and all(item["country_code"] == "VN" for item in vietnam)
    assert "VNSGN" in {item["code"] for item in vietnam}


@pytest.mark.parametrize("mode", ["SEA", "AIR"])
def test_top_trade_partners_are_ranked(app, mode):
    """상위 교역국 20개국은 어떤 운송 모드에서도 목록에 있고 순위가 매겨집니다."""

    countries = planning_service.list_countries(mode, "destination")["data"]
    ranked = {c["code"]: c["trade_rank"] for c in countries if c.get("trade_rank")}
    assert set(ranked) == set(planning_service.TOP_TRADE_PARTNERS)
    assert sorted(ranked.values()) == list(range(1, len(planning_service.TOP_TRADE_PARTNERS) + 1))
    assert ranked["CN"] == 1 and ranked["US"] == 2


def test_schedules_cover_every_region(app, shipment_payload):
    """Every destination region has mock rates (Middle East, Africa, South America…)."""

    fastest = {}
    for destination in ("VNSGN", "USLAX", "DEHAM", "AEJEA", "ZADUR", "BRSSZ", "AUSYD"):
        payload = {**shipment_payload, "destination_code": destination}
        items = planning_service.search_schedules(payload)["items"]
        assert items, f"{destination} 스케줄 없음"
        fastest[destination] = min(item["transit_days"] for item in items)

    # 남미는 북미와 다른 구간으로 계산합니다.
    assert fastest["BRSSZ"] > fastest["USLAX"]
    assert fastest["VNSGN"] < fastest["USLAX"] < fastest["DEHAM"]


def test_direct_input_location_accepted(app, shipment_payload):
    payload = {
        **shipment_payload,
        "destination_code": "USZZZ",
        "destination_custom": {"name": "Private Terminal", "country_code": "US"},
    }
    schedules = planning_service.search_schedules(payload)
    assert schedules["items"]
    payload["schedule_id"] = schedules["items"][0]["schedule_id"]
    shipment = planning_service.create_shipment(payload)
    assert shipment.destination_code == "USZZZ"
    assert shipment.destination_name == "Private Terminal"
    assert shipment.destination_country == "US"


@pytest.mark.parametrize("custom,field", [
    ({"name": "No Country", "country_code": ""}, "destination_country"),
    ({"name": "", "country_code": "US"}, "destination_name"),
    ({"name": "Bad Code", "country_code": "US"}, "destination_code"),
    ({"name": "Korean Destination", "country_code": "KR"}, "destination_code"),
])
def test_direct_input_validation(app, shipment_payload, custom, field):
    code = "A!" if custom["name"] == "Bad Code" else "USZZZ"
    payload = {**shipment_payload, "destination_code": code, "destination_custom": custom}
    with pytest.raises(ValidationError) as info:
        planning_service.search_schedules(payload)
    assert info.value.field == field


def test_unknown_code_without_direct_input_rejected(app, shipment_payload):
    with pytest.raises(ValidationError) as info:
        planning_service.search_schedules({**shipment_payload, "destination_code": "ZZZZZ"})
    assert info.value.field == "destination_code"


def test_schedules_are_mock_labeled_and_sorted(app, shipment_payload):
    by_price = planning_service.search_schedules({**shipment_payload, "sort": "price"})
    prices = [item["freight_usd"] for item in by_price["items"]]
    assert prices == sorted(prices)
    assert by_price["source"] == "mock"
    assert all(item["source"] == "mock" for item in by_price["items"])
    assert all(item["etd"] >= shipment_payload["requested_departure_date"] for item in by_price["items"])

    by_duration = planning_service.search_schedules({**shipment_payload, "sort": "duration"})
    days = [item["transit_days"] for item in by_duration["items"]]
    assert days == sorted(days)


def test_air_rejects_sea_only_incoterms(app, shipment_payload):
    payload = {**shipment_payload, "transport_mode": "AIR", "origin_code": "ICN", "destination_code": "LAX",
               "incoterms": "FOB", "schedule_id": "x"}
    with pytest.raises(ValidationError) as info:
        planning_service.create_shipment(payload)
    assert info.value.field == "incoterms"


def test_route_rejects_port_for_air(app, shipment_payload):
    with pytest.raises(ValidationError) as info:
        planning_service.search_schedules({**shipment_payload, "transport_mode": "AIR"})
    assert info.value.field == "origin_code"


def test_create_shipment(create_shipment):
    shipment = create_shipment()
    assert shipment.shipment_id == f"EXP-{date.today().year}-00001"
    assert shipment.status == "quoted"
    assert shipment.schedule_source == "mock"
    assert shipment.cargo.total_cbm == 30.0
    assert shipment.planned_eta == shipment.eta
    assert shipment.cargo_ready_date == shipment.etd - timedelta(days=4)
    assert shipment.total_cost_krw > 0
    second = create_shipment()
    assert second.shipment_id.endswith("00002")


def test_create_shipment_rejects_unknown_schedule(app, shipment_payload):
    with pytest.raises(ValidationError) as info:
        planning_service.create_shipment({**shipment_payload, "schedule_id": "FAKE-2026-01-01"})
    assert info.value.field == "schedule_id"


def test_net_weight_cannot_exceed_gross(app, shipment_payload, cargo_input):
    payload = {**shipment_payload, "cargo": {**cargo_input, "net_weight_kg": 999_999}}
    payload["schedule_id"] = planning_service.search_schedules(payload)["items"][0]["schedule_id"]
    with pytest.raises(ValidationError):
        planning_service.create_shipment(payload)


def test_required_parties_not_invented(app, shipment_payload):
    payload = {**shipment_payload, "exporter_name": ""}
    payload["schedule_id"] = planning_service.search_schedules(payload)["items"][0]["schedule_id"]
    with pytest.raises(ValidationError) as info:
        planning_service.create_shipment(payload)
    assert info.value.field == "exporter_name"
