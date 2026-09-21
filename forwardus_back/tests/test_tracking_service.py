"""Tracking event and ETA monitoring tests."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.processors.cashflow_calculator import calculate_cash_flow
from app.services import ServiceError, assistant_service, tracking_service
from app.validators import ValidationError


def test_mock_events_advance_in_order_and_update_status(create_shipment):
    shipment = create_shipment()
    codes = [tracking_service.advance_mock(shipment)["event_code"] for _ in range(5)]
    assert codes == ["booking_confirmed", "container_pickup", "gate_in", "customs_cleared", "departed"]
    assert shipment.status == "departed"
    assert all(event.source == "mock" for event in shipment.tracking_events)


def test_tracking_completes_and_stops(create_shipment):
    shipment = create_shipment()
    for _ in range(10):
        tracking_service.advance_mock(shipment)
    assert shipment.status == "delivered"
    with pytest.raises(ServiceError):
        tracking_service.advance_mock(shipment)


def test_eta_change_creates_exception_event(create_shipment):
    shipment = create_shipment()
    original = shipment.eta
    change = tracking_service.update_eta_manually(shipment, {"new_eta": (original + timedelta(days=4)).isoformat()})
    assert change["delay_days"] == 4
    assert shipment.eta == original + timedelta(days=4)
    assert shipment.planned_eta == original
    assert shipment.delay_days == 4
    event = [e for e in shipment.tracking_events if e.event_code == "eta_changed"][0]
    assert event.is_exception and event.previous_eta == original and event.source == "manual"

    guide = assistant_service.exception_guide(shipment)
    assert guide["has_exception"]
    assert "Buyer에게 ETA 변경 안내" in guide["actions"]


def test_same_eta_is_not_a_change(create_shipment):
    shipment = create_shipment()
    assert tracking_service.update_eta_manually(shipment, {"new_eta": shipment.eta.isoformat()}) is None
    assert shipment.tracking_events == []


def test_eta_before_etd_rejected(create_shipment):
    shipment = create_shipment()
    with pytest.raises(ValidationError):
        tracking_service.update_eta_manually(shipment, {"new_eta": (shipment.etd - timedelta(days=1)).isoformat()})


def test_manual_event_validation(create_shipment):
    shipment = create_shipment()
    with pytest.raises(ValidationError):
        tracking_service.add_manual_event(shipment, {"event_code": "teleported", "event_date": "2026-10-01"})
    tracking_service.add_manual_event(shipment, {"event_code": "departed", "event_date": "2026-10-01"})
    assert shipment.status == "departed"


def test_cancelled_shipment_not_trackable(create_shipment):
    from app.services import shipment_service

    shipment = create_shipment()
    shipment_service.transition(shipment, "cancel")
    with pytest.raises(ServiceError):
        tracking_service.advance_mock(shipment)


def test_cash_flow_peak_funding():
    from datetime import date

    result = calculate_cash_flow([
        {"label": "Production", "amount_krw": -15_000_000, "due_date": date(2026, 10, 1)},
        {"label": "Freight", "amount_krw": -3_000_000, "due_date": date(2026, 10, 10)},
        {"label": "Buyer", "amount_krw": 30_000_000, "due_date": date(2026, 11, 30)},
    ])
    assert result["peak_funding_need_krw"] == 18_000_000
    assert result["net_krw"] == 12_000_000


def test_assistant_never_declares_export_allowed(create_shipment):
    shipment = create_shipment()
    readiness = assistant_service.export_readiness(shipment)
    text = " ".join(readiness["lines"])
    assert "수출 가능합니다" not in text
    assert "필요 없습니다" not in text
    assert {item["status"] for item in readiness["items"]} <= {"confirmed", "check_required", "not_applicable", "unknown"}
    assert any("FDA" in item["title"] for item in readiness["items"])
