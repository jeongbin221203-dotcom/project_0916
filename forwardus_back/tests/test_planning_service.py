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
    assert [p["code"] for p in ports] == ["KRPUS"]
    airports = planning_service.search_locations("los angeles", "AIR", "destination")["data"]
    assert [a["code"] for a in airports] == ["LAX"]
    assert planning_service.search_locations("USLAX", "SEA", "origin")["data"] == []


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
