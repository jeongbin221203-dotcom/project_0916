"""Tracking timeline, event recording, and ETA monitoring."""

from __future__ import annotations

from datetime import date, datetime

from app.collectors import tracking_client
from app.models.tracking_event import EVENT_LABELS, TRACKING_EVENTS
from app.processors.schedule_calculator import check_buyer_deadline
from app.repositories import shipment_repository, tracking_repository
from app.services import ServiceError
from app.validators import ValidationError
from app.validators.shipment_validator import optional_text, parse_date

EVENT_STATUS = {
    "booking_confirmed": "booked",
    "container_pickup": "booked",
    "gate_in": "booked",
    "customs_cleared": "booked",
    "departed": "departed",
    "in_transit": "in_transit",
    "arrived": "arrived",
    "import_customs": "arrived",
    "out_for_delivery": "arrived",
    "delivered": "delivered",
}
TRACKABLE_STATUSES = {"quoted", "booked", "departed", "in_transit", "arrived"}


def build_timeline(shipment) -> dict:
    events = tracking_repository.list_events(shipment)
    progress = {event.event_code: event for event in events if event.event_code in EVENT_STATUS}
    reached = [code for code in TRACKING_EVENTS if code in progress]
    last_index = TRACKING_EVENTS.index(reached[-1]) if reached else -1

    steps = []
    for index, code in enumerate(TRACKING_EVENTS):
        event = progress.get(code)
        if event:
            state = "current" if index == last_index and code != "delivered" else "done"
        else:
            state = "pending"
        steps.append({"code": code, "label": EVENT_LABELS[code], "state": state, "event": event})

    sources = sorted({event.source for event in events})
    return {
        "steps": steps,
        "events": list(reversed(events)),
        "exceptions": [event for event in events if event.is_exception],
        "sources": sources,
        "deadline": check_buyer_deadline(shipment.eta, shipment.buyer_required_date, shipment.transport_mode)
        if shipment.eta else None,
    }


def _apply_status(shipment, event_code: str) -> None:
    if shipment.status in ("closed", "cancelled"):
        return
    target = EVENT_STATUS.get(event_code)
    order = ["quoted", "booked", "departed", "in_transit", "arrived", "delivered"]
    if target and shipment.status in order and order.index(target) > order.index(shipment.status):
        shipment.status = target


def monitor_eta(shipment, new_eta: date, source: str, event_time: datetime | None = None) -> dict | None:
    """Compare a reported ETA with the current one and record a change event."""

    if shipment.eta is None or new_eta == shipment.eta:
        return None
    previous = shipment.eta
    delta = (new_eta - previous).days
    tracking_repository.add_event(
        shipment,
        event_code="eta_changed",
        event_time=event_time or datetime.now(),
        location="",
        description=f"ETA {previous.isoformat()} → {new_eta.isoformat()} ({delta:+d}일)",
        source=source,
        is_exception=delta > 0,
        previous_eta=previous,
        new_eta=new_eta,
    )
    shipment.eta = new_eta
    return {"previous_eta": previous, "current_eta": new_eta, "delay_days": delta}


def _ensure_trackable(shipment) -> None:
    if shipment.status not in TRACKABLE_STATUSES:
        raise ServiceError(f"현재 상태({shipment.status_label})에서는 Tracking 이벤트를 추가할 수 없습니다.",
                           "NOT_TRACKABLE")


def advance_mock(shipment) -> dict:
    """Pull the next event from the (mock) tracking provider."""

    _ensure_trackable(shipment)
    recorded = [event.event_code for event in shipment.tracking_events]
    result = tracking_client.fetch_next_event(shipment, recorded)
    if not result["success"]:
        raise ServiceError(result["message"], result["error_code"], 502)

    event_data = result["data"]["event"]
    if event_data is None:
        raise ServiceError("모든 Tracking 이벤트가 완료되었습니다.", "TRACKING_COMPLETE")

    event_time = datetime.fromisoformat(event_data["event_time"])
    tracking_repository.add_event(
        shipment,
        event_code=event_data["event_code"],
        event_time=event_time,
        location=event_data["location"],
        description=event_data["description"],
        source=result["source"],
    )
    _apply_status(shipment, event_data["event_code"])
    change = None
    if result["data"]["current_eta"]:
        change = monitor_eta(shipment, date.fromisoformat(result["data"]["current_eta"]), result["source"], event_time)
    shipment_repository.commit()
    return {"event_code": event_data["event_code"], "eta_change": change, "source": result["source"]}


def add_manual_event(shipment, form: dict) -> None:
    _ensure_trackable(shipment)
    code = str(form.get("event_code") or "")
    if code not in TRACKING_EVENTS:
        raise ValidationError("이벤트 유형을 선택해주세요.", "event_code")
    event_date = parse_date(form.get("event_date"), "이벤트 일자", field="event_date")
    tracking_repository.add_event(
        shipment,
        event_code=code,
        event_time=datetime.combine(event_date, datetime.min.time()),
        location=optional_text(form.get("location"), max_length=200),
        description=optional_text(form.get("description")),
        source="manual",
    )
    _apply_status(shipment, code)
    shipment_repository.commit()


def update_eta_manually(shipment, form: dict) -> dict | None:
    _ensure_trackable(shipment)
    new_eta = parse_date(form.get("new_eta"), "새 ETA", field="new_eta")
    if shipment.etd and new_eta < shipment.etd:
        raise ValidationError("ETA는 ETD보다 빠를 수 없습니다.", "new_eta")
    change = monitor_eta(shipment, new_eta, "manual")
    shipment_repository.commit()
    return change
