"""Shipment tracking provider.

Without a live tracking API, the mock provider replays the standard event
sequence one step at a time. Results are always marked ``source = mock``.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta

from app.collectors.base_client import load_mock, ok

EVENT_SEQUENCE = [
    "booking_confirmed",
    "container_pickup",
    "gate_in",
    "customs_cleared",
    "departed",
    "in_transit",
    "arrived",
    "import_customs",
    "out_for_delivery",
    "delivered",
]

AIR_LABEL_OVERRIDES = {"container_pickup": "Cargo Pick Up", "gate_in": "Warehouse Received"}


def _stable_hash(text: str) -> int:
    return sum((index + 1) * ord(char) for index, char in enumerate(text))


def fetch_next_event(shipment, recorded_codes: list[str]) -> dict:
    """Return the next event after the ones already recorded, plus the carrier's current ETA."""

    # TODO: call the live provider via base_client.request_json when TRACKING_API_KEY is configured.

    remaining = [code for code in EVENT_SEQUENCE if code not in recorded_codes]
    if not remaining:
        return ok({"event": None, "current_eta": shipment.eta.isoformat() if shipment.eta else None}, "mock")

    code = remaining[0]
    etd, eta = shipment.etd, shipment.eta
    origin, destination = shipment.origin_name, shipment.destination_name
    event_dates = {
        "booking_confirmed": etd - timedelta(days=6),
        "container_pickup": etd - timedelta(days=4),
        "gate_in": etd - timedelta(days=3),
        "customs_cleared": etd - timedelta(days=2),
        "departed": etd,
        "in_transit": etd + timedelta(days=1),
        "arrived": eta,
        "import_customs": eta + timedelta(days=1),
        "out_for_delivery": eta + timedelta(days=2),
        "delivered": eta + timedelta(days=3),
    }
    locations = {code_: origin for code_ in EVENT_SEQUENCE[:5]}
    locations.update({"in_transit": "At sea" if shipment.transport_mode == "SEA" else "In flight"})
    locations.update({code_: destination for code_ in EVENT_SEQUENCE[6:]})

    current_eta = eta
    # Deterministic mock disruption: some shipments report a revised ETA once in transit.
    delays = load_mock("tracking_delays")
    if code == "in_transit" and shipment.eta == shipment.planned_eta:
        delay = delays["delay_days_by_bucket"][_stable_hash(shipment.shipment_id) % len(delays["delay_days_by_bucket"])]
        if shipment.transport_mode == "AIR":
            delay = min(delay, 1)
        current_eta = eta + timedelta(days=delay)

    label = AIR_LABEL_OVERRIDES.get(code) if shipment.transport_mode == "AIR" else None
    event = {
        "event_code": code,
        "event_time": datetime.combine(event_dates[code], time(9, 0)).isoformat(),
        "location": locations[code],
        "description": label or "",
    }
    return ok({"event": event, "current_eta": current_eta.isoformat() if current_eta else None}, "mock")
